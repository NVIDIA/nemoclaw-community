#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"
RUN_DIR="$EXAMPLE_DIR/.run"
mkdir -p "$RUN_DIR"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$EXAMPLE_DIR/.env"
  set +a
fi

SANDBOX_NAME="${SANDBOX_NAME:-deep-research-worker}"
WORKER_PORT="${DEEPAGENTS_SERVICE_PORT:-9050}"
POLICY_PATH="$EXAMPLE_DIR/policies/deep-research-worker.yaml"
SKILL_DIR="/sandbox/.openclaw/skills/deep-research"
CLIENT_PATH="$SKILL_DIR/scripts/deep_research_client.py"
WRAPPER_HOST_PATH="$RUN_DIR/deep-research"

echo "== 1/4 start host-side worker =="
(cd "$EXAMPLE_DIR" && docker compose up -d --build)

echo "== 2/4 wait for worker health =="
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${WORKER_PORT}/healthz" >/dev/null 2>&1; then
    echo "Worker is healthy on http://127.0.0.1:${WORKER_PORT}"
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${WORKER_PORT}/healthz" >/dev/null

if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell not found; the host-side worker is running, but the sandbox"
  echo "policy and skill were not installed."
  exit 0
fi

if ! openshell sandbox list 2>/dev/null | grep -qE "^[[:space:]]*${SANDBOX_NAME}[[:space:]]"; then
  echo "Sandbox '${SANDBOX_NAME}' was not found. The worker is running, but the"
  echo "policy and skill were not installed. Create or select a sandbox, then"
  echo "re-run this script."
  exit 0
fi

echo "== 3/4 apply sandbox policy =="
openshell policy set --policy "$POLICY_PATH" --wait "$SANDBOX_NAME"

echo "== 4/4 install skill and CLI wrapper =="
openshell sandbox exec --name "$SANDBOX_NAME" -- mkdir -p "$SKILL_DIR/scripts" /sandbox/bin
openshell sandbox cp "$EXAMPLE_DIR/src/SKILL.md" "${SANDBOX_NAME}:${SKILL_DIR}/SKILL.md"
openshell sandbox cp "$EXAMPLE_DIR/src/deep_research_client.py" "${SANDBOX_NAME}:${CLIENT_PATH}"

cat >"$WRAPPER_HOST_PATH" <<EOF
#!/usr/bin/env bash
export DEEPAGENTS_ENDPOINT_URL="\${DEEPAGENTS_ENDPOINT_URL:-http://host.openshell.internal:${WORKER_PORT}}"
export DEEPAGENTS_SERVICE_SECRET="\${DEEPAGENTS_SERVICE_SECRET:-${DEEPAGENTS_SERVICE_SECRET:-}}"
exec python3 "${CLIENT_PATH}" "\$@"
EOF

chmod +x "$WRAPPER_HOST_PATH"
openshell sandbox cp "$WRAPPER_HOST_PATH" "${SANDBOX_NAME}:/sandbox/bin/deep-research"
openshell sandbox exec --name "$SANDBOX_NAME" -- chmod +x /sandbox/bin/deep-research "$CLIENT_PATH"

echo "Bring-up complete."
echo "Run local checks with: bash scripts/verify.sh"
echo "Run from the sandbox with: /sandbox/bin/deep-research --help"
