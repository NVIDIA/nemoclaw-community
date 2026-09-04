#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# End-to-end suite for a running swarm. Discovers bots; asserts isolation, api,
# chat, mesh, and tracing. Exit code is the number of failures (capped at 1).
#
#   ./swarm test        or        tests/e2e.sh
set -uo pipefail

SWARM_ROOT="${SWARM_ROOT:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)}"
export SWARM_ROOT
# Load config + modules exactly the way ./swarm does, without running a command.
ENV_FILE="${SWARM_ENV:-$SWARM_ROOT/swarm.env}"
[[ -f "$ENV_FILE" ]] || { echo "no $ENV_FILE"; exit 1; }
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a
: "${TRACING:=on}" "${OTLP_PORT:=4319}" "${LANGSMITH_PROJECT:=hermes-swarm}" "${INFERENCE_CONTEXT_LENGTH:=131072}" "${INFERENCE_MAX_TOKENS:=8192}"
INFERENCE_KEY_FILE="${INFERENCE_KEY_FILE/#\~/$HOME}"; SWARM_STATE="${SWARM_STATE/#\~/$HOME}"
LANGSMITH_KEY_FILE="${LANGSMITH_KEY_FILE:-}"; LANGSMITH_KEY_FILE="${LANGSMITH_KEY_FILE/#\~/$HOME}"
if [[ -z "${HOST_API_ADDR:-}" ]]; then
  if [[ "$(uname -s)" == Darwin ]]; then HOST_API_ADDR=127.0.0.1; else HOST_API_ADDR="$BRIDGE_IP"; fi
fi
export INFERENCE_KEY_FILE LANGSMITH_KEY_FILE SWARM_STATE HOST_API_ADDR
for m in common preflight image policy sandbox bot extras host mesh tracing verify; do
  # shellcheck disable=SC1090
  source "$SWARM_ROOT/lib/$m.sh"
done
_real_home=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6 || true)   # Linux
[[ -n "$_real_home" ]] || _real_home=$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | awk '{print $2}')   # macOS
[[ -d "${_real_home:-}" ]] && export HOME="$_real_home"
unset HERMES_HOME HERMES_PROFILE   # see the note in ./swarm
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

PASS=0; FAIL=0
t_pass() { printf '    %sPASS%s  %s\n' "$C_GREEN" "$C_OFF" "$1"; PASS=$((PASS + 1)); }
t_fail() { printf '    %sFAIL%s  %s  [%s]\n' "$C_RED" "$C_OFF" "$1" "$2"; FAIL=$((FAIL + 1)); }
check() { # check "label" got want
  if [[ "$2" == "$3" ]]; then t_pass "$1"; else t_fail "$1" "got '$2' want '$3'"; fi
}
section() { printf '\n  %s%s%s\n' "$C_BOLD" "$1" "$C_OFF"; }

# Rows in the sandbox's sessions table. sqlite3 is not in the image, so ask the
# Hermes venv. The query goes through two shells (ours, then sh -c in the
# sandbox), which eats any quoting; a heredoc into python's stdin avoids that.
sandbox_session_count() {
  sbx "$1" '$H - <<PY 2>/dev/null
import sqlite3
print(sqlite3.connect("/sandbox/.hermes/state.db").execute("select count(*) from sessions").fetchone()[0])
PY' 60 | tail -1
}

BOTS_FOUND=(); while IFS= read -r line; do [[ -n "$line" ]] && BOTS_FOUND+=("$line"); done < <(bot_list)
N=${#BOTS_FOUND[@]}
printf '  bots: %s\n' "${BOTS_FOUND[*]:-none}"
(( N >= 1 )) || { echo "no bots; run ./swarm up"; exit 1; }

section "1  preflight"
if preflight_run >/dev/null 2>&1; then t_pass "preflight clean"; else t_fail "preflight" "see ./swarm doctor"; fi

section "2  image"
check "image $(image_tag) present" "$(image_present && echo yes || echo no)" yes
baked=$(docker run --rm --entrypoint /bin/sh "$(image_tag)" -c 'cat /etc/hermes-ref' 2>/dev/null)
check "image baked ref" "$baked" "$HERMES_REF"

section "3  sandboxes and isolation"
# On Linux the host has /proc namespaces to compare against. On macOS the
# sandboxes run inside the Colima/Docker Desktop VM, so compare against the
# VM's PID 1 instead (a plain container on the same daemon sees it).
if [[ -r /proc/self/ns/pid ]]; then
  HOST_NS="$(hostname) $(readlink /proc/self/ns/pid | tr -dc 0-9) $(readlink /proc/self/ns/net | tr -dc 0-9) $(readlink /proc/self/ns/mnt | tr -dc 0-9)"
else
  HOST_NS=$(docker run --rm --pid=host --network=host alpine:3 sh -c 'printf "%s %s %s %s" "$(hostname)" "$(readlink /proc/1/ns/pid | tr -dc 0-9)" "$(readlink /proc/1/ns/net | tr -dc 0-9)" "$(readlink /proc/1/ns/mnt | tr -dc 0-9)"' 2>/dev/null || echo "vm 0 0 0")
fi
# bash 3.2 (macOS) has no associative arrays; keep namespaces in a parallel list.
NS_LIST=()
for b in "${BOTS_FOUND[@]}"; do
  sb=$(sandbox_of "$b")
  check "$sb Ready" "$(sandbox_phase "$sb")" Ready
  ns=$(sandbox_ns "$sb"); NS_LIST+=("$ns")
  check "$sb pid-ns differs from host" "$([[ "$(cut -d' ' -f2 <<<"$ns")" != "$(cut -d' ' -f2 <<<"$HOST_NS")" ]] && echo yes || echo no)" yes
  check "$sb net-ns differs from host" "$([[ "$(cut -d' ' -f3 <<<"$ns")" != "$(cut -d' ' -f3 <<<"$HOST_NS")" ]] && echo yes || echo no)" yes
  mark="MARK-$b-$RANDOM"
  sbx "$sb" "echo $mark > /sandbox/whoami.txt" 30 >/dev/null
  check "$sb owns its own /sandbox/whoami.txt" "$(sbx "$sb" 'cat /sandbox/whoami.txt' 30 | tail -1)" "$mark"
  ver=$(sbx "$sb" '$H -m hermes_cli.main --version 2>/dev/null | head -1' 60 | tail -1)
  check "$sb hermes is ${HERMES_REF#v}" "$(grep -q "${HERMES_REF#v}" <<<"$ver" && echo yes || echo no)" yes
done
if (( N >= 2 )); then
  a="${BOTS_FOUND[0]}"; c="${BOTS_FOUND[1]}"
  check "pid-ns differs between $a and $c" "$([[ "$(cut -d' ' -f2 <<<"${NS_LIST[0]}")" != "$(cut -d' ' -f2 <<<"${NS_LIST[1]}")" ]] && echo yes || echo no)" yes
fi

section "4  egress policy (deny by default)"
for b in "${BOTS_FOUND[@]}"; do
  sb=$(sandbox_of "$b")
  # The egress proxy refuses the CONNECT tunnel for an unlisted host, so curl
  # sees "CONNECT tunnel failed, response 403" and reports 000. Plain http gets
  # a clean 403. Either way the request never left the sandbox.
  code=$(sbx "$sb" 'curl -s -o /dev/null -w "%{http_code}" --max-time 8 http://example.com/' 30 | tail -1)
  check "$sb cannot reach example.com (http)" "$code" 403
  out=$(sbx "$sb" 'curl -sS -o /dev/null --max-time 8 https://example.com/ 2>&1 || true' 30 | tail -1)
  check "$sb cannot reach example.com (https)" "$([[ "$out" == *"response 403"* ]] && echo denied || echo "$out")" denied
  read -r ihost iport _ < <(_inference_endpoint)
  scheme=https; [[ "$iport" == 80 ]] && scheme=http
  code=$(sbx "$sb" "curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H \"Authorization: Bearer \$(grep ^INFERENCE_API_KEY= /sandbox/.hermes/.env | cut -d= -f2-)\" $INFERENCE_BASE_URL/models" 40 | tail -1)
  check "$sb reaches inference endpoint" "$code" 200
done

section "5  api_server on the bridge"
for b in "${BOTS_FOUND[@]}"; do
  port=$(bot_port "$b"); key=$(read_secret "$(bot_key_file "$b")")
  check "$b :$port /v1/models with key" "$(http_code "http://$HOST_API_ADDR:$port/v1/models" -H "Authorization: Bearer $key")" 200
  check "$b :$port rejects a wrong key" "$(http_code "http://$HOST_API_ADDR:$port/v1/models" -H "Authorization: Bearer wrong")" 401
  check "$b exactly one bridge forward" "$(pgrep -f "forward service --target-port $port " | wc -l | tr -d ' ')" 1
done

section "6  chat turn runs inside the sandbox"
for b in "${BOTS_FOUND[@]}"; do
  sb=$(sandbox_of "$b")
  before=$(sandbox_session_count "$sb")
  # Unique token per run: the api_server dedupes an identical request and can
  # answer from its response store without running a new turn.
  tok="$b-E2E-$RANDOM$RANDOM"
  reply=$(timeout 240 hermes -p "$b" chat -q "Reply with exactly: $tok" 2>/dev/null | grep -ao "$tok" | head -1)
  check "$b answers via host profile" "$reply" "$tok"
  # The session row is committed after the reply has streamed; give it a moment.
  after=$before
  for _ in 1 2 3 4 5 6; do
    after=$(sandbox_session_count "$sb")
    [[ "${after:-0}" -gt "${before:-0}" ]] && break
    sleep 5
  done
  check "$b turn recorded in the sandbox state.db ($before -> $after)" "$([[ "${after:-0}" -gt "${before:-0}" ]] && echo yes || echo no)" yes
done

section "7  tool execution happens in the sandbox"
b="${BOTS_FOUND[0]}"; sb=$(sandbox_of "$b")
out=$(timeout 240 hermes -p "$b" chat -q 'Use the terminal tool to run exactly: hostname; then reply with only the output.' 2>/dev/null | strip_ansi)
inside=$(sbx "$sb" 'hostname' 30 | tail -1)
check "$b terminal tool ran in $sb (hostname $inside)" "$(grep -q "$inside" <<<"$out" && echo yes || echo no)" yes
check "$b did not run on the host" "$(grep -q "$(hostname)" <<<"$out" && echo leaked || echo no)" no

section "8  mesh: teammate handoff with a planted secret"
if (( N >= 2 )); then
  a="${BOTS_FOUND[0]}"; c="${BOTS_FOUND[1]}"
  secret="E2E-$(openssl rand -hex 4)"
  sbx "$(sandbox_of "$c")" "echo $secret > /sandbox/secret.txt" 30 >/dev/null
  check "$a lists $c as teammate" "$(mesh_peers_of "$a" | grep -cx "$c")" 1
  check "$c lists $a as teammate" "$(mesh_peers_of "$c" | grep -cx "$a")" 1
  out=$(timeout 400 hermes -p "$a" chat -q "Use message_teammate to ask teammate '$c' to run: cat /sandbox/secret.txt and return the exact contents. Reply with only the value they return." 2>/dev/null | strip_ansi)
  check "$a retrieved $c's secret through message_teammate" "$(grep -q "$secret" <<<"$out" && echo yes || echo no)" yes
else
  dim "one bot only; mesh skipped"
fi

section "9  tracing (NeMo Relay -> collector)"
if [[ "$TRACING" == on ]]; then
  check "collector running" "$(collector_running && echo yes || echo no)" yes
  for b in "${BOTS_FOUND[@]}"; do
    sb=$(sandbox_of "$b")
    check "$b relay-plugins.toml present" "$(sbx "$sb" 'test -f /sandbox/.hermes/relay-plugins.toml && echo yes || echo no' 30 | tail -1)" yes
    check "$b relay env set" "$(sbx "$sb" 'grep -c ^HERMES_NEMO_RELAY_PLUGINS_TOML= /sandbox/.hermes/.env' 30 | tail -1)" 1
    check "$b relay plugins active (gateway log)" "$(tracing_bot_active "$b" && echo yes || echo no)" yes
    check "$b can reach collector" "$(sbx "$sb" "curl -s -o /dev/null -w '%{http_code}' --max-time 8 -X POST -H 'Content-Type: application/json' -d '{}' http://host.openshell.internal:$OTLP_PORT/v1/traces" 30 | tail -1)" 200
  done
  read -r s0 f0 < <(tracing_counts)
  timeout 240 hermes -p "${BOTS_FOUND[0]}" chat -q "Reply with exactly: TRACE-PING" >/dev/null 2>&1
  sleep 12
  read -r s1 f1 < <(tracing_counts)
  check "collector exported more spans after a turn ($s0 -> $s1)" "$([[ "$s1" -gt "$s0" ]] && echo yes || echo no)" yes
  check "no failed span exports" "$f1" 0
else
  dim "tracing off"
fi

section "10 host profiles (Desktop roster)"
for b in "${BOTS_FOUND[@]}"; do
  check "$b host profile exists" "$([[ -f "$HOME/.hermes/profiles/$b/config.yaml" ]] && echo yes || echo no)" yes
  [[ "${HOST_GATEWAY:-on}" == on ]] && check "$b host profile running" "$(host_profile_state "$b")" running
done

section "11 multimodal examples (only when those bots exist)"
if bot_exists nemoclaw-vision 2>/dev/null; then
  sb=$(sandbox_of nemoclaw-vision)
  check "nemoclaw-vision declares vision in the sandbox" "$(sbx "$sb" 'grep -c "supports_vision: true" /sandbox/.hermes/config.yaml' 30 | tail -1)" 1
  check "nemoclaw-vision shim declares vision" "$(hermes -p nemoclaw-vision config get model.supports_vision 2>/dev/null | tail -1)" true
  # A 64x64 white PNG with a red square, no PIL needed.
  img=$(mktemp /tmp/e2e-img.XXXXXX.png)
  python3 - "$img" <<'PY'
import struct, sys, zlib
W=H=64; rows=[]
for y in range(H):
    row=bytearray([0])
    for x in range(W): row += bytes([255,0,0]) if (16<=x<48 and 16<=y<48) else bytes([255,255,255])
    rows.append(bytes(row))
def chunk(t,d): return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
open(sys.argv[1],"wb").write(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",W,H,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(rows),9))+chunk(b"IEND",b""))
PY
  out=$(timeout 240 hermes -p nemoclaw-vision chat --image "$img" -q "One sentence: what shape and colour is in this image? No tools." 2>/dev/null | strip_ansi | tr 'A-Z' 'a-z')
  rm -f "$img"
  check "nemoclaw-vision saw the image (red square)" "$(grep -q "red" <<<"$out" && grep -qE "square|rectangle" <<<"$out" && echo yes || echo no)" yes
  check "nemoclaw-vision did not say it cannot see" "$(grep -q "cannot see\|can't see\|unable to see" <<<"$out" && echo blind || echo no)" no
else
  dim "nemoclaw-vision not present; skipped"
fi
if bot_exists nemoclaw-vss 2>/dev/null; then
  sb=$(sandbox_of nemoclaw-vss)
  check "nemoclaw-vss has the vss plugin" "$(sbx "$sb" 'test -f /sandbox/.hermes/plugins/vss/plugin.yaml && echo yes || echo no' 30 | tail -1)" yes
  check "nemoclaw-vss has the vss-video skill" "$(sbx "$sb" 'test -f /sandbox/.hermes/skills/vss-video/SKILL.md && echo yes || echo no' 30 | tail -1)" yes
  check "nemoclaw-vss has clips" "$(sbx "$sb" 'ls /sandbox/videos/*.mp4 2>/dev/null | wc -l | tr -d " "' 30 | tail -1 | awk '{print ($1>0)?"yes":"no"}')" yes
  if [[ -n "${VSS_BASE_URL:-}" ]]; then
    check "nemoclaw-vss policy names RT-VLM" "$(policy_endpoints "$sb" | grep -c "vss-rtvlm")" 1
    other="${BOTS_FOUND[0]}"; [[ "$other" == nemoclaw-vss ]] && other="${BOTS_FOUND[1]}"
    check "$other policy does NOT name RT-VLM" "$(policy_endpoints "$(sandbox_of "$other")" | grep -c "vss-rtvlm")" 0
    vhost="${VSS_BASE_URL#*://}"; vhost="${vhost%%/*}"
    check "$other cannot reach RT-VLM (403)" "$(sbx "$(sandbox_of "$other")" "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://$vhost/v1/models" 30 | tail -1)" 403
    check "nemoclaw-vss can reach RT-VLM (200)" "$(sbx "$sb" "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://$vhost/v1/models" 30 | tail -1)" 200
    out=$(timeout 400 hermes -p nemoclaw-vss chat -q "Use vss_describe_video on forklift-training.mp4 and reply with the first two timestamped lines only." 2>/dev/null | strip_ansi)
    check "nemoclaw-vss described the clip with timestamps" "$(grep -qE '\[[0-9]{2}:[0-9]{2}-[0-9]{2}:[0-9]{2}\]' <<<"$out" && echo yes || echo no)" yes
  else
    dim "VSS_BASE_URL not set; RT-VLM checks skipped"
  fi
else
  dim "nemoclaw-vss not present; skipped"
fi

# ── 12. lifecycle: add reconciles, down respects BOTS, ownership, failed delete ──
# Uses a throwaway bot so the fleet above is never disturbed. Skipped with
# SWARM_TEST_LIFECYCLE=off (it costs about four minutes).
if [[ "${SWARM_TEST_LIFECYCLE:-on}" == on ]]; then
  section "12. lifecycle"
  tb=nemoclaw-zz-lifecycle; tsb=$(sandbox_of "$tb"); anchor="${BOTS_FOUND[0]}"
  bot_exists "$tb" 2>/dev/null && "$SWARM_ROOT/swarm" rm "$tb" --yes >/dev/null 2>&1

  # add: the new bot exists, and the EXISTING bots were reconciled (soul lists it, gateway restarted)
  before=$(sbx "$(sandbox_of "$anchor")" 'stat -c %Y /sandbox/.hermes/SOUL.md' 30 | tail -1)
  "$SWARM_ROOT/swarm" add "$tb" --role "You are a lifecycle test bot. Reply with exactly what you are asked." >/dev/null 2>&1
  check "add: $tb created and Ready" "$(sandbox_phase "$tsb")" Ready
  check "add: ownership marker written (host)" "$(test -s "$SWARM_STATE/owned/$tsb" && echo yes || echo no)" yes
  check "add: ownership marker written (sandbox)" "$(sbx "$tsb" 'test -s /sandbox/.hermes/.swarm-owner && echo yes || echo no' 30 | tail -1)" yes
  after=$(sbx "$(sandbox_of "$anchor")" 'stat -c %Y /sandbox/.hermes/SOUL.md' 30 | tail -1)
  check "add: existing bot $anchor soul was rewritten" "$([[ "$after" -gt "$before" ]] && echo yes || echo no)" yes
  check "add: $anchor peers include $tb" "$(mesh_peers_of "$anchor" | grep -cx "$tb")" 1
  check "add: $anchor host profile has dropbox marker state" "$(test -f "$HOME/.hermes/profiles/$anchor/.swarm-owner" && echo yes || echo no)" yes

  # down (default scope) must NOT remove a bot outside BOTS
  "$SWARM_ROOT/swarm" down --yes >/dev/null 2>&1 || true
  check "down: $tb (not in BOTS) survives swarm down" "$(sandbox_phase "$tsb")" Ready
  # ...and the BOTS bots need to come back for the rest of the suite
  "$SWARM_ROOT/swarm" up >/dev/null 2>&1 || true
  check "up: $anchor restored after down" "$(sandbox_phase "$(sandbox_of "$anchor")")" Ready

  # ownership: a foreign sandbox with our name is refused by create/restore/destroy
  fk=$(bot_key_file "$tb"); fp=$(bot_port_file "$tb")
  mv "$SWARM_STATE/owned/$tsb" "$SWARM_STATE/owned/$tsb.bak"
  check "ownership: restore refuses a sandbox without our marker" \
    "$( (bot_restore "$tb" >/dev/null 2>&1 && echo ran) || echo refused)" refused
  check "ownership: destroy refuses it and keeps the key" \
    "$( (bot_destroy "$tb" >/dev/null 2>&1 && echo ran) || { test -s "$fk" && echo refused-kept; })" refused-kept
  check "ownership: sandbox untouched" "$(sandbox_phase "$tsb")" Ready
  mv "$SWARM_STATE/owned/$tsb.bak" "$SWARM_STATE/owned/$tsb"

  # failed delete keeps state: simulate by making `openshell sandbox delete` a no-op
  mkdir -p /tmp/swarm-fakebin; cat > /tmp/swarm-fakebin/openshell <<'EOS'
#!/usr/bin/env bash
if [[ "$1 $2" == "sandbox delete" ]]; then exit 0; fi
exec "$(command -v -p openshell 2>/dev/null || ls /usr/local/bin/openshell "$HOME/.local/bin/openshell" 2>/dev/null | head -1)" "$@"
EOS
  chmod +x /tmp/swarm-fakebin/openshell
  check "failed delete: bot_destroy returns non-zero" \
    "$( (PATH="/tmp/swarm-fakebin:$PATH" bot_destroy "$tb" >/dev/null 2>&1 && echo ok) || echo nonzero)" nonzero
  check "failed delete: key kept" "$(test -s "$fk" && echo yes || echo no)" yes
  check "failed delete: port kept" "$(test -s "$fp" && echo yes || echo no)" yes
  check "failed delete: host profile kept" "$(hermes profile list 2>/dev/null | strip_ansi | awk '{print $1}' | grep -cx "$tb")" 1
  rm -rf /tmp/swarm-fakebin

  # real removal, then the others are reconciled back
  "$SWARM_ROOT/swarm" rm "$tb" --yes >/dev/null 2>&1
  check "rm: $tb gone" "$(sandbox_exists "$tsb" && echo present || echo gone)" gone
  check "rm: key removed" "$(test -s "$fk" && echo yes || echo no)" no
  check "rm: $anchor peers no longer include $tb" "$(mesh_peers_of "$anchor" | grep -cx "$tb")" 0
  check "rm: ownership marker removed" "$(test -e "$SWARM_STATE/owned/$tsb" && echo yes || echo no)" no
else
  dim "lifecycle section skipped (SWARM_TEST_LIFECYCLE=off)"
fi

# ── 13. tracing opt-out ───────────────────────────────────────────────────────
if [[ "${TRACING:-on}" == on && "${SWARM_TEST_LIFECYCLE:-on}" == on ]]; then
  section "13. tracing opt-out"
  anchor="${BOTS_FOUND[0]}"; asb=$(sandbox_of "$anchor")
  check "tracing on: relay env present in $anchor" "$(sbx "$asb" 'grep -c HERMES_NEMO_RELAY_PLUGINS_TOML /sandbox/.hermes/.env' 30 | tail -1)" 1
  # swarm.env is sourced after the environment, so the file value wins; turning
  # tracing off is an edit to swarm.env, which is what this does on a copy.
  offenv=$(mktemp /tmp/swarm-off.XXXXXX); sed 's/^TRACING=.*/TRACING=off/' "$ENV_FILE" > "$offenv"
  grep -q '^TRACING=off' "$offenv" || printf 'TRACING=off\n' >> "$offenv"
  SWARM_ENV="$offenv" "$SWARM_ROOT/swarm" up >/dev/null 2>&1 || true
  rm -f "$offenv"
  check "tracing off: relay env removed from $anchor" "$(sbx "$asb" 'grep -c HERMES_NEMO_RELAY_PLUGINS_TOML /sandbox/.hermes/.env' 30 | tail -1)" 0
  check "tracing off: relay toml removed" "$(sbx "$asb" 'test -f /sandbox/.hermes/relay-plugins.toml && echo yes || echo no' 30 | tail -1)" no
  check "tracing off: collector container removed" "$(docker inspect swarm-otel >/dev/null 2>&1 && echo present || echo gone)" gone
  "$SWARM_ROOT/swarm" up >/dev/null 2>&1 || true
  check "tracing on again: relay env restored" "$(sbx "$asb" 'grep -c HERMES_NEMO_RELAY_PLUGINS_TOML /sandbox/.hermes/.env' 30 | tail -1)" 1
  check "tracing on again: collector running" "$(docker inspect -f '{{.State.Running}}' swarm-otel 2>/dev/null)" true
fi

# ── 14. image forwarding is opt-in ────────────────────────────────────────────
# The property lives in the plugin: without with_images nothing crosses, with
# it exactly the turn's images do. Proved two ways. First, in-sandbox, by
# calling the plugin's own function against a fake teammate that counts the
# image parts it receives (no model in the loop, so no soul can add the flag).
# Second, live: after the reviewer's model handles a photo, the number of
# results that report a forwarded image never exceeds the number of calls that
# set the flag. Both Python probes travel as base64 to avoid quoting layers.
if bot_exists nemoclaw-vision 2>/dev/null && (( ${#BOTS_FOUND[@]} >= 2 )); then
  section "14. image forwarding is opt-in"
  other="${BOTS_FOUND[0]}"; [[ "$other" == nemoclaw-vision ]] && other="${BOTS_FOUND[1]}"
  osb=$(sandbox_of "$other")
  probe=$(cat <<'PY'
import json, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, "/sandbox/.hermes/plugins")
import teammates.tools as t
got = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        parts = body["messages"][-1]["content"]
        got.append(sum(1 for p in (parts if isinstance(parts, list) else []) if p.get("type") == "image_url"))
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}).encode())
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
t._load_peers = lambda: {"fake": {"url": "http://127.0.0.1:%d" % port, "note": ""}}
t._peer_key = lambda n: "k"
t.remember_turn_images("s", [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}])
r1 = json.loads(t.message_teammate({"teammate": "fake", "message": "what colour is the attached image?"}, session_id="s"))
r2 = json.loads(t.message_teammate({"teammate": "fake", "message": "what colour is the attached image?", "with_images": True}, session_id="s"))
print("default_images_sent", got[0], "default_reported", r1.get("images_forwarded", 0))
print("optin_images_sent", got[1], "optin_reported", r2.get("images_forwarded", 0))
PY
)
  pb=$(printf '%s' "$probe" | b64)
  out=$(sbx "$osb" "printf '%s' '$pb' | base64 -d > /sandbox/p14.py && \$H /sandbox/p14.py; rm -f /sandbox/p14.py" 120 | grep -E "^(default|optin)_")
  check "plugin: default call sends 0 image parts" "$(awk '/^default_images_sent/{print $2}' <<<"$out")" 0
  check "plugin: default call reports 0 forwarded" "$(awk '/^default_images_sent/{print $4}' <<<"$out")" 0
  check "plugin: with_images sends 1 image part" "$(awk '/^optin_images_sent/{print $2}' <<<"$out")" 1
  check "plugin: with_images reports 1 forwarded" "$(awk '/^optin_images_sent/{print $4}' <<<"$out")" 1

  img=$(mktemp /tmp/swarm-red.XXXXXX.png)
  python3 - "$img" <<'PY'
import struct, zlib, sys
W=H=16; rows=[bytes([0])+bytes([255,0,0])*W for _ in range(H)]
def ch(t,d): return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
open(sys.argv[1],"wb").write(b"\x89PNG\r\n\x1a\n"+ch(b"IHDR",struct.pack(">IIBBBBB",W,H,8,2,0,0,0))+ch(b"IDAT",zlib.compress(b"".join(rows)))+ch(b"IEND",b""))
PY
  T0=$(date +%s); sleep 1
  timeout 300 hermes -p "$other" chat --image "$img" -q "what colour is this image? ask nemoclaw-vision (probe $RANDOM)" >/dev/null 2>&1
  rm -f "$img"
  audit_py=$(cat <<'PY'
import sqlite3, json, sys, re
since = float(sys.argv[1]); c = sqlite3.connect("/sandbox/.hermes/state.db")
calls = flagged = forwarded = 0
for role, content, tools in c.execute("select role,content,tool_calls from messages where timestamp > ? order by id", (since,)):
    if tools:
        for t in json.loads(tools):
            a = t["function"].get("arguments", "{}"); a = json.loads(a) if isinstance(a, str) else a
            inner = a.get("arguments", a) if isinstance(a, dict) else {}
            if isinstance(inner, dict) and "teammate" in inner:
                calls += 1; flagged += 1 if inner.get("with_images") else 0
    if role == "tool":
        m = re.search(r'"images_forwarded":\s*(\d+)', content or "")
        if m and int(m.group(1)) > 0: forwarded += 1
print("calls", calls, "flagged", flagged, "forwarded_results", forwarded)
PY
)
  ab=$(printf '%s' "$audit_py" | b64)
  audit=$(sbx "$osb" "printf '%s' '$ab' | base64 -d > /sandbox/a14.py && \$H /sandbox/a14.py $T0; rm -f /sandbox/a14.py" 60 | grep '^calls')
  check "live: a teammate call was made" "$(awk '{print ($2>0)?"yes":"no"}' <<<"$audit")" yes
  check "live: forwarded results never exceed flagged calls" "$(awk '{print ($6<=$4)?"yes":"no"}' <<<"$audit")" yes
fi

printf '\n  ==============================================\n  SUMMARY: %d passed, %d failed\n  ==============================================\n' "$PASS" "$FAIL"
(( FAIL == 0 ))
