#!/usr/bin/env bash
# Recovery helper for DGX Spark / restricted network namespaces.
#
# Use only if OpenClaw CLI calls show:
#   gateway closed (1006)
# and /tmp/gateway.log mentions:
#   uv_interface_addresses returned Unknown system error
#
# Run after scripts/apply-omni-subagent.sh, which disables unused default plugins
# and creates the writable task/plugin-runtime paths.
set -euo pipefail

SANDBOX="${SANDBOX:-hclaw}"
DOCKER_CTR="${DOCKER_CTR:-openshell-cluster-nemoclaw}"

need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing required command: $1" >&2
        exit 1
    fi
}
need docker
need openshell

kexec() {
    docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- "$@"
}

echo "→ sandbox: $SANDBOX"
openshell sandbox get "$SANDBOX" >/dev/null

# The normal NemoClaw entrypoint emits /tmp/nemoclaw-proxy-env.sh and preload
# guards. If the gateway died early, seed those files without requiring the
# entrypoint to stay running.
echo "→ seeding NemoClaw proxy/guard files if needed"
kexec /bin/bash -lc 'if [ ! -f /tmp/nemoclaw-proxy-env.sh ]; then (unset NEMOCLAW_MODEL_OVERRIDE NEMOCLAW_INFERENCE_API_OVERRIDE NEMOCLAW_CONTEXT_WINDOW NEMOCLAW_MAX_TOKENS NEMOCLAW_REASONING; timeout 10 /usr/local/bin/nemoclaw-start) >/tmp/nemoclaw-start-seed.log 2>&1 || true; fi'

echo "→ starting OpenClaw gateway with NemoClaw proxy/guard environment"
openshell sandbox exec -n "$SANDBOX" -- bash -lc 'if [ -f /tmp/gateway-manual.pid ]; then kill $(cat /tmp/gateway-manual.pid) 2>/dev/null || true; fi; pkill -x openclaw-gateway 2>/dev/null || true; source /tmp/nemoclaw-proxy-env.sh; export OPENSHELL_SANDBOX=1 HOME=/sandbox OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; nohup openclaw gateway run --port 18789 >/tmp/gateway-manual.log 2>&1 & echo $! > /tmp/gateway-manual.pid'

for _ in $(seq 1 60); do
    status_out=$(openshell sandbox exec -n "$SANDBOX" -- python3 - <<'PY' 2>&1 || true
import socket
try:
    with socket.create_connection(("127.0.0.1", 18789), timeout=2):
        print("Connectivity probe: ok")
except OSError as exc:
    print(f"Connectivity probe: failed ({exc})")
    raise SystemExit(1)
PY
)
    if grep -q 'Connectivity probe: ok' <<<"$status_out"; then
        echo "✓ gateway connectivity probe ok"
        printf '%s
' "$status_out"
        exit 0
    fi
    sleep 1
done

echo "✗ gateway did not become ready. Last status:"
printf '%s
' "$status_out"
echo "Check:"
echo "  openshell sandbox exec -n $SANDBOX -- tail -n 120 /tmp/gateway-manual.log"
exit 1
