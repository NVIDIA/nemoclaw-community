#!/usr/bin/env bash
# Smoke-test an already patched OpenClaw Omni demo sandbox.
#
# This script assumes scripts/apply-omni-subagent.sh has already completed for
# the target sandbox. It does not require NVIDIA_API_KEY on the host; it verifies
# the in-sandbox provider config without printing the key.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
if [[ -f "$HERE/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HERE/.env"
    set +a
fi

SANDBOX="${SANDBOX:-hclaw}"
DOCKER_CTR="${DOCKER_CTR:-openshell-cluster-nemoclaw}"
WORKSPACE="/sandbox/.openclaw-data/workspace"
DIRECT_RETRIES="${DIRECT_RETRIES:-2}"
DIRECT_TIMEOUT_SECONDS="${DIRECT_TIMEOUT_SECONDS:-180}"
DELEGATION_WAIT_SECONDS="${DELEGATION_WAIT_SECONDS:-180}"

log() { printf '[omni-demo] %s\n' "$*"; }
fail() {
    printf '[omni-demo] ERROR: %s\n' "$*" >&2
    exit 1
}
need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        fail "missing required command: $1"
    fi
}

need docker
need openshell
need python3

kexec() {
    docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- "$@"
}

sandbox_exec() {
    openshell sandbox exec -n "$SANDBOX" -- "$@"
}

run_agent() {
    sandbox_exec bash -lc "source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; $*"
}

assert_contains_red() {
    local label="$1"
    local text="$2"
    if ! grep -Eiq 'red|solid' <<<"$text"; then
        printf '%s\n' "$text" >&2
        fail "$label did not describe the red test image"
    fi
}

log "sandbox: $SANDBOX"
openshell sandbox get "$SANDBOX" >/dev/null

log "checking OpenClaw config and workspace"
kexec bash -lc 'python3 - <<PY
import json
import os
cfg = json.load(open("/sandbox/.openclaw/openclaw.json"))
providers = cfg["models"]["providers"]
agents = {agent["id"]: agent for agent in cfg["agents"]["list"]}
unused_plugins = [
    "acpx", "alibaba", "amazon-bedrock", "amazon-bedrock-mantle",
    "anthropic", "anthropic-vertex", "arcee", "bonjour", "browser",
    "byteplus", "chutes", "cloudflare-ai-gateway", "codex", "comfy",
    "copilot-proxy", "deepgram", "deepseek", "device-pair", "document-extract",
    "elevenlabs", "fal", "fireworks", "github-copilot", "google",
    "groq", "huggingface", "kilocode", "kimi", "litellm", "lmstudio",
    "memory-core", "microsoft", "microsoft-foundry", "minimax", "mistral", "moonshot",
    "ollama", "openai", "opencode", "opencode-go", "openrouter", "nvidia",
    "phone-control",
    "qianfan", "qqbot", "qwen", "runway", "sglang", "stepfun",
    "synthetic", "talk-voice", "tencent", "together", "venice", "vercel-ai-gateway",
    "vllm", "volcengine", "voyage", "vydra", "web-readability", "xai",
    "xiaomi", "zai",
]
plugin_entries = cfg.get("plugins", {}).get("entries", {})
checks = {
    "provider nvidia-omni": "nvidia-omni" in providers,
    "provider apiKey": providers.get("nvidia-omni", {}).get("apiKey", "").startswith("nvapi-"),
    "agent main": "main" in agents,
    "agent vision-operator": "vision-operator" in agents,
    "vision workspace": agents.get("vision-operator", {}).get("workspace") == "/sandbox/.openclaw-data/workspace",
    "timeout": cfg["agents"]["defaults"].get("timeoutSeconds", 0) >= 300,
    "subagent concurrency": cfg["agents"]["defaults"].get("subagents", {}).get("maxConcurrent") == 4,
    "agents md": os.path.exists("/sandbox/.openclaw-data/workspace/AGENTS.md"),
    "tools": os.path.exists("/sandbox/.openclaw-data/workspace/TOOLS.md"),
    "auth data": os.path.exists("/sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json"),
    "auth active": os.path.exists("/sandbox/.openclaw/agents/vision-operator/agent/auth-profiles.json"),
    "plugin deps": os.path.islink("/sandbox/.openclaw/plugin-runtime-deps") or os.path.isdir("/sandbox/.openclaw/plugin-runtime-deps"),
    "plugins globally disabled": cfg.get("plugins", {}).get("enabled") is False,
    "memory plugin slot disabled": cfg.get("plugins", {}).get("slots", {}).get("memory") == "none",
    "unused plugins disabled": all(plugin_entries.get(plugin_id, {}).get("enabled") is False for plugin_id in unused_plugins),
}
for name, ok in checks.items():
    print(f"{name}: {ok}")
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("failed verification checks: " + ", ".join(failed))
PY'

log "checking agent registry"
agents_output="$(sandbox_exec bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; openclaw agents list')"
if grep -q '\[plugins\].*staging bundled runtime deps' <<<"$agents_output"; then
    printf '%s\n' "$agents_output" >&2
    fail "openclaw agents list staged unrelated plugin runtime deps; re-run scripts/apply-omni-subagent.sh"
fi
grep -q 'vision-operator' <<<"$agents_output" || fail "openclaw agents list did not include vision-operator"
grep -q 'nvidia-omni' <<<"$agents_output" || fail "openclaw agents list did not include nvidia-omni model"

log "checking nvidia policy allows node"
policy_output="$(openshell policy get "$SANDBOX" --full)"
if ! sed -n '/^  nvidia:/,/^  [a-z]/p' <<<"$policy_output" | grep -q '/usr/local/bin/node'; then
    fail "nvidia policy block does not include /usr/local/bin/node"
fi

log "probing nvidia-omni provider auth"
provider_probe="$(kexec bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; node <<"NODE"
const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync("/sandbox/.openclaw/openclaw.json", "utf8"));
const provider = cfg.models.providers["nvidia-omni"];
const body = {
  model: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
  messages: [{ role: "user", content: "Reply with ok." }],
  max_tokens: 16,
};
(async () => {
  const res = await fetch(provider.baseUrl + "/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "authorization": `Bearer ${provider.apiKey}`,
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  console.log("status=" + res.status);
  if (!res.ok) {
    console.log(text.slice(0, 500).replace(provider.apiKey, "[redacted]"));
    process.exit(1);
  }
})().catch(err => {
  console.error(err && err.stack || err);
  process.exit(1);
});
NODE' 2>&1)" || {
    printf '%s\n' "$provider_probe" >&2
    fail "nvidia-omni provider probe failed; verify the NVIDIA API key has Omni access"
}
grep -q 'status=200' <<<"$provider_probe" || {
    printf '%s\n' "$provider_probe" >&2
    fail "nvidia-omni provider probe returned an unexpected status"
}

log "checking gateway connectivity"
gateway_output="$(sandbox_exec python3 - <<'PY'
import socket
try:
    with socket.create_connection(("127.0.0.1", 18789), timeout=5):
        print("Connectivity probe: ok")
except OSError as exc:
    print(f"Connectivity probe: failed ({exc})")
    raise SystemExit(1)
PY
)"
grep -q 'Connectivity probe: ok' <<<"$gateway_output" || {
    printf '%s\n' "$gateway_output" >&2
    fail "gateway connectivity probe did not pass"
}

log "creating and uploading red test image"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
python3 - "$tmpdir/red.png" <<'PY'
import base64
import sys
from pathlib import Path
png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/lk3Q3wAAAABJRU5ErkJggg=="
Path(sys.argv[1]).write_bytes(base64.b64decode(png))
PY
if ! openshell sandbox upload "$SANDBOX" "$tmpdir/red.png" "$WORKSPACE/" >/dev/null 2>&1; then
    log "openshell upload failed; falling back to kubectl tee"
    docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- \
        tee "$WORKSPACE/red.png" < "$tmpdir/red.png" >/dev/null
fi
kexec test -s "$WORKSPACE/red.png"

log "running direct vision-operator image test"
direct_output=""
direct_passed=0
for attempt in $(seq 1 "$DIRECT_RETRIES"); do
    session_id="direct-vision-smoke-$(date +%s)-$attempt"
    if direct_output="$(run_agent "timeout $DIRECT_TIMEOUT_SECONDS openclaw agent --json --agent vision-operator --thinking off --message 'Use the image tool to inspect $WORKSPACE/red.png. Retry the image tool once if it returns Request was aborted or Image failed. Return exactly one sentence describing the image. /no_think' --session-id $session_id --timeout $DIRECT_TIMEOUT_SECONDS" 2>&1)"; then
        if grep -Eiq 'red|solid' <<<"$direct_output"; then
            direct_passed=1
            break
        fi
    fi
    log "direct vision attempt $attempt did not pass; retrying if attempts remain"
done
if [[ "$direct_passed" != "1" ]]; then
    printf '%s\n' "$direct_output" >&2
    fail "direct vision test failed after $DIRECT_RETRIES attempt(s)"
fi
assert_contains_red "direct vision output" "$direct_output"

log "running main-agent delegation test"
kexec rm -f "$WORKSPACE/image-description.md"
delegation_output="$(run_agent "openclaw agent --agent main --thinking off --message 'Use agents_list to confirm vision-operator is available, then delegate to vision-operator with sessions_spawn. In the sub-agent message, tell it: Use the image tool to inspect $WORKSPACE/red.png, retry the image tool once if it returns Request was aborted or Image failed, return exactly one sentence describing it, use --thinking off behavior if available, and include /no_think. Write the final one-sentence description to $WORKSPACE/image-description.md and tell me what you wrote.' --session-id main-vision-delegation-smoke-$(date +%s) --timeout 420" 2>&1 || true)"
log "$delegation_output"

description=""
for _ in $(seq 1 "$DELEGATION_WAIT_SECONDS"); do
    if sandbox_exec test -s "$WORKSPACE/image-description.md" >/dev/null 2>&1; then
        description="$(sandbox_exec cat "$WORKSPACE/image-description.md")"
        break
    fi
    sleep 1
done
[[ -n "$description" ]] || fail "main-agent delegation did not write image-description.md"
assert_contains_red "delegation output file" "$description"

log "running missing-image negative test"
kexec rm -f "$WORKSPACE/missing-image-description.md"
missing_started="$(date +%s)"
missing_output="$(run_agent "openclaw agent --agent vision-operator --thinking off --message 'Use the image tool to inspect $WORKSPACE/does-not-exist.png. If it fails, report the error and do not write $WORKSPACE/missing-image-description.md. /no_think' --session-id missing-image-smoke-$missing_started --timeout 180" 2>&1 || true)"
if sandbox_exec test -e "$WORKSPACE/missing-image-description.md" >/dev/null 2>&1; then
    fail "missing-image test created a phantom output file"
fi
if ! grep -Eiq 'fail|error|not found|no such' <<<"$missing_output"; then
    missing_trace="$(kexec bash -lc "python3 - <<'PY'
import glob
import os
start = float(${missing_started})
needle = 'Local media file not found: ${WORKSPACE}/does-not-exist.png'
for path in glob.glob('/sandbox/.openclaw/agents/vision-operator/sessions/*.jsonl') + glob.glob('/tmp/openclaw-*/*.log'):
    try:
        if os.path.getmtime(path) < start - 1:
            continue
        with open(path, errors='ignore') as f:
            text = f.read()
    except OSError:
        continue
    if needle in text:
        print(path)
        raise SystemExit(0)
raise SystemExit(1)
PY" 2>/dev/null || true)"
    if [[ -z "$missing_trace" ]]; then
        printf '%s\n' "$missing_output" >&2
        fail "missing-image test did not report or log a clean failure"
    fi
fi

log "all checks passed"
