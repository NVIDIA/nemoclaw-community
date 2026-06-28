#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Recover the financial assistant booth runtime on a Brev host.
#
# Run from examples/financial-analyst-hermes on the Brev instance. The script
# restarts the known-good path:
#
#   browser -> finance UI :18080 -> Hermes sandbox :8642
#           -> host NeMo Relay :4040 -> compatible chat API
#           -> Phoenix :6006

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-.env}"
UI_PORT="${FINANCE_UI_PORT:-18080}"
RELAY_PORT="${FINANCE_RELAY_PORT:-4040}"
PHOENIX_PORT="${FINANCE_PHOENIX_PORT:-6006}"
LOG_DIR="${FINANCE_RUNTIME_LOG_DIR:-$ROOT/.runtime}"
SKIP_BUILD="${FINANCE_SKIP_BUILD:-1}"

mkdir -p "$LOG_DIR"

log() {
  printf '[finance-recover] %s\n' "$*"
}

die() {
  printf '[finance-recover] ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

load_env() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example to .env first"
  set -a
  set +u
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set -u
  set +a

  : "${FINANCE_API_URL:?set FINANCE_API_URL in $ENV_FILE, including /v1}"
  : "${FINANCE_API_KEY:?set FINANCE_API_KEY in $ENV_FILE}"
  : "${FINANCE_MODEL:?set FINANCE_MODEL in $ENV_FILE}"

  export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$FINANCE_API_KEY}"
  export PHOENIX_PROJECT_NAME="${PHOENIX_PROJECT_NAME:-financial-assistant-relay}"
}

resolve_hermes_container() {
  if [[ -n "${FINANCE_HERMES_CONTAINER:-}" ]]; then
    docker inspect "$FINANCE_HERMES_CONTAINER" >/dev/null 2>&1 ||
      die "FINANCE_HERMES_CONTAINER=$FINANCE_HERMES_CONTAINER does not exist"
    printf '%s\n' "$FINANCE_HERMES_CONTAINER"
    return
  fi

  local candidates=()
  while IFS= read -r name; do
    if docker exec "$name" sh -lc \
      'test -d /sandbox/.hermes && test -x /opt/hermes/.venv/bin/python' \
      >/dev/null 2>&1; then
      candidates+=("$name")
    fi
  done < <(docker ps --format '{{.Names}}')

  if [[ "${#candidates[@]}" -eq 0 ]]; then
    die "could not find a running Hermes sandbox container; set FINANCE_HERMES_CONTAINER"
  fi

  for name in "${candidates[@]}"; do
    if docker exec "$name" sh -lc \
      'ss -ltn 2>/dev/null | grep -Eq ":(18642|8642) "' \
      >/dev/null 2>&1; then
      printf '%s\n' "$name"
      return
    fi
  done

  if [[ "${#candidates[@]}" -gt 1 ]]; then
    printf '[finance-recover] candidates:\n' >&2
    printf '  %s\n' "${candidates[@]}" >&2
    die "multiple Hermes-like containers found; set FINANCE_HERMES_CONTAINER to the intended one"
  fi

  printf '%s\n' "${candidates[0]}"
}

container_ip() {
  local container="$1"
  docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container" |
    awk '{print $1}'
}

relay_bin() {
  if command -v nemo-relay >/dev/null 2>&1; then
    command -v nemo-relay
    return
  fi
  if [[ -x /home/ubuntu/.local/bin/nemo-relay ]]; then
    printf '%s\n' /home/ubuntu/.local/bin/nemo-relay
    return
  fi
  die "nemo-relay was not found in PATH or /home/ubuntu/.local/bin"
}

start_phoenix() {
  require docker
  log "starting Phoenix on 127.0.0.1:$PHOENIX_PORT"
  docker compose -f observability/phoenix-compose.yml up -d

  for _ in {1..30}; do
    curl -fsS "http://127.0.0.1:$PHOENIX_PORT/" >/dev/null 2>&1 && return
    sleep 1
  done
  die "Phoenix did not become reachable on 127.0.0.1:$PHOENIX_PORT"
}

write_relay_config() {
  mkdir -p .nemo-relay
  cat > .nemo-relay/plugins.toml <<EOF
version = 1

[[components]]
kind = "observability"
enabled = true

[components.config.atif]
enabled = true
output_directory = "/tmp/finance-assistant-atif"

[components.config.openinference]
enabled = true
transport = "http_binary"
endpoint = "http://127.0.0.1:${PHOENIX_PORT}/v1/traces"
service_name = "financial-assistant-agent"
timeout_millis = 3000

[components.config.openinference.resource_attributes]
"openinference.project.name" = "${PHOENIX_PROJECT_NAME}"
"deployment.environment" = "brev-demo"
"demo.channel" = "web-outlook"
EOF
}

start_relay() {
  local bin
  bin="$(relay_bin)"
  write_relay_config

  log "stopping stale NeMo Relay listeners on port $RELAY_PORT"
  pkill -f "nemo-relay.*${RELAY_PORT}" >/dev/null 2>&1 || true
  sleep 1

  log "starting NeMo Relay on 0.0.0.0:$RELAY_PORT"
  nohup "$bin" \
    --bind "0.0.0.0:$RELAY_PORT" \
    --openai-base-url "$FINANCE_API_URL" \
    > "$LOG_DIR/nemo-relay.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/nemo-relay.pid"

  for _ in {1..30}; do
    if curl -fsS "http://127.0.0.1:$RELAY_PORT/v1/models" \
      -H "Authorization: Bearer $FINANCE_API_KEY" >/dev/null 2>&1; then
      return
    fi
    if ! kill -0 "$(cat "$LOG_DIR/nemo-relay.pid")" 2>/dev/null; then
      sed -n '1,160p' "$LOG_DIR/nemo-relay.log" >&2 || true
      die "NeMo Relay exited during startup"
    fi
    sleep 1
  done

  sed -n '1,160p' "$LOG_DIR/nemo-relay.log" >&2 || true
  die "NeMo Relay did not become reachable on 127.0.0.1:$RELAY_PORT"
}

refresh_hermes_files() {
  local container="$1"
  log "refreshing Hermes SOUL and nemo-relay plugin in $container"
  docker exec "$container" sh -lc \
    'mkdir -p /sandbox/.hermes/plugins/nemo-relay /usr/local/lib/nemoclaw/bin /tmp'
  docker cp agents/hermes/SOUL.md "$container:/sandbox/.hermes/SOUL.md"
  docker cp agents/hermes/plugins/nemo-relay/. \
    "$container:/sandbox/.hermes/plugins/nemo-relay/"
  docker cp agents/hermes/relay-hooks.yaml "$container:/tmp/finance-relay-hooks.yaml"
  docker cp agents/hermes/nemo-relay/finalize-hook \
    "$container:/usr/local/lib/nemoclaw/bin/nemo-relay-finalize-hook"

  docker exec "$container" sh -lc '
    set -eu
    chown -R sandbox:sandbox /sandbox/.hermes/plugins/nemo-relay /sandbox/.hermes/SOUL.md
    chmod -R g+rwX /sandbox/.hermes/plugins/nemo-relay
    chmod g+rw /sandbox/.hermes/SOUL.md
    chmod 0755 /usr/local/lib/nemoclaw/bin/nemo-relay-finalize-hook
    if ! grep -q "nemo-relay" /sandbox/.hermes/config.yaml; then
      cat /tmp/finance-relay-hooks.yaml >> /sandbox/.hermes/config.yaml 2>/dev/null || true
    fi
    grep -q "nemo-relay" /sandbox/.hermes/config.yaml
  ' || die "Hermes config does not enable nemo-relay; merge agents/hermes/relay-hooks.yaml into /sandbox/.hermes/config.yaml"
}

restart_hermes() {
  local container="$1"
  log "restarting Hermes with NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:$RELAY_PORT"
  docker exec -i "$container" sh -s -- "$RELAY_PORT" <<'SH'
set -eu
relay_port="$1"
pid="$(pgrep -f '^/opt/hermes/.venv/bin/python /usr/local/bin/hermes gateway run' || true)"
if [ -n "$pid" ]; then
  kill $pid || true
  sleep 1
fi
rm -f /tmp/gateway.log
touch /tmp/gateway.log
chown gateway:sandbox /tmp/gateway.log
chmod 660 /tmp/gateway.log
if ! ss -ltn 2>/dev/null | grep -q ':8642 '; then
  nohup socat TCP-LISTEN:8642,bind=0.0.0.0,fork,reuseaddr TCP:127.0.0.1:18642 \
    >/tmp/socat-8642.log 2>&1 < /dev/null &
fi
gosu gateway sh -lc "set -e; . /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; export HOME=/sandbox HERMES_HOME=/sandbox/.hermes; export NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:${relay_port}; export NO_PROXY=\"\${NO_PROXY:+\$NO_PROXY,}host.openshell.internal,172.18.0.1,127.0.0.1,localhost\" no_proxy=\"\${no_proxy:+\$no_proxy,}host.openshell.internal,172.18.0.1,127.0.0.1,localhost\"; umask 0007; nohup hermes gateway run >/tmp/gateway.log 2>&1 < /dev/null &"
sleep 2
pid="$(pgrep -f '^/opt/hermes/.venv/bin/python /usr/local/bin/hermes gateway run' || true)"
[ -n "$pid" ]
tr '\0' '\n' < "/proc/$pid/environ" | grep -q '^NEMO_RELAY_GATEWAY_URL='
SH
}

build_ui() {
  if [[ "$SKIP_BUILD" == "1" ]]; then
    log "skipping UI build because FINANCE_SKIP_BUILD=1"
    return
  fi
  require npm
  [[ -d node_modules ]] || npm install
  npm run build
}

start_ui() {
  local hermes_url="$1"
  require python3

  log "stopping stale finance UI listeners on port $UI_PORT"
  pkill -f "python3 scripts/finance_ui_server.py.*${UI_PORT}" >/dev/null 2>&1 || true
  sleep 1

  log "starting finance UI on 0.0.0.0:$UI_PORT through $hermes_url"
  nohup python3 scripts/finance_ui_server.py \
    --env-file "$ENV_FILE" \
    --host 0.0.0.0 \
    --port "$UI_PORT" \
    --api-url "$hermes_url" \
    --auth-env FINANCE_API_KEY \
    --model "$FINANCE_MODEL" \
    --upstream-label "Hermes + Relay + Phoenix" \
    --phoenix-url "http://127.0.0.1:$PHOENIX_PORT/graphql" \
    > "$LOG_DIR/finance-ui.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/finance-ui.pid"

  for _ in {1..30}; do
    curl -fsS "http://127.0.0.1:$UI_PORT/health" >/dev/null 2>&1 && return
    sleep 1
  done
  sed -n '1,160p' "$LOG_DIR/finance-ui.log" >&2 || true
  die "finance UI did not become reachable on 127.0.0.1:$UI_PORT"
}

verify_skills_trace() {
  log "verifying UI -> Hermes skills question -> skill_view tool spans in Phoenix"
  python3 - "$UI_PORT" "$FINANCE_MODEL" <<'PY'
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

port, model = sys.argv[1:3]
started = datetime.now(timezone.utc)
body = json.dumps(
    {
        "model": model,
        "stream": False,
        "max_tokens": 1200,
        "reasoning_effort": "high",
        "messages": [
            {
                "role": "user",
                "content": "What skills do you have? Please inspect your installed finance skills and answer concisely.",
            }
        ],
    }
).encode()
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/chat/completions",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Finance-Run-Id": "recover-skills-trace",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=180) as response:
    payload = json.load(response)
message = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
if "financial-market-snapshot" not in message or "sec-company-facts" not in message:
    raise SystemExit("skills response did not name the expected finance skills")

deadline = time.time() + 30
latest = []
while time.time() < deadline:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/phoenix/recent", timeout=20
    ) as response:
        trace_payload = json.load(response)
    latest = trace_payload.get("spans", [])
    fresh_tools = []
    for span in latest:
        if span.get("name") != "skill_view" or span.get("kind") != "tool":
            continue
        raw = span.get("started_at") or ""
        if not raw:
            continue
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if when >= started:
            fresh_tools.append(span)
    if fresh_tools:
        print(message[:500])
        print(f"fresh_skill_view_spans={len(fresh_tools)} trace={fresh_tools[0].get('trace_id')}")
        sys.exit(0)
    time.sleep(2)

print(json.dumps(latest[:8], indent=2))
raise SystemExit("Phoenix did not show a fresh skill_view tool span")
PY
}

print_summary() {
  local hermes_url="$1"
  cat <<EOF

Financial assistant recovery complete.

Live services on the Brev host:
  UI:      http://127.0.0.1:${UI_PORT}
  Hermes:  ${hermes_url}
  Relay:   http://127.0.0.1:${RELAY_PORT}
  Phoenix: http://127.0.0.1:${PHOENIX_PORT}

Useful checks:
  curl -sf http://127.0.0.1:${UI_PORT}/health
  curl -sf http://127.0.0.1:${UI_PORT}/api/phoenix/recent | python3 -m json.tool

EOF
}

require docker
require curl
load_env
container="$(resolve_hermes_container)"
ip="$(container_ip "$container")"
hermes_url="${FINANCE_HERMES_API_URL:-http://${ip:-127.0.0.1}:8642}"

log "using Hermes container: $container"
start_phoenix
start_relay
refresh_hermes_files "$container"
restart_hermes "$container"
build_ui
start_ui "$hermes_url"
verify_skills_trace
print_summary "$hermes_url"
