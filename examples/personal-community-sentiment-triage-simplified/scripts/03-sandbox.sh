#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 3 of 3: Build the sandbox image and create the sandbox.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

for v in SLACK_BOT_TOKEN SLACK_APP_TOKEN TAVILY_API_KEY; do
  [[ -n "${!v:-}" ]] || { echo "Missing $v — populate $EXAMPLE_DIR/.env" >&2; exit 1; }
done
[[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]] || {
  echo "Missing GITHUB_TOKEN or GH_TOKEN — populate $EXAMPLE_DIR/.env" >&2
  exit 1
}
command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

STAGED_DOCKERFILE="$EXAMPLE_DIR/.Dockerfile.staged"
trap 'rm -f "$STAGED_DOCKERFILE"' EXIT

# ── Build CHANNELS_B64 and ALLOWED_IDS_B64 ─────────────────────────────
read -r -d '' _BUILD_B64_PY <<'PY' || true
import base64
import json
import os

channels = ["slack"]
allowed = {}
v = (os.environ.get("SLACK_ALLOWED_IDS") or "").strip()
if v:
    allowed["slack"] = [s.strip() for s in v.split(",") if s.strip()]

print(base64.b64encode(json.dumps(channels).encode()).decode())
print(base64.b64encode(json.dumps(allowed).encode()).decode())
PY
mapfile -t _B64 < <(python3 -c "$_BUILD_B64_PY")
CHANNELS_B64="${_B64[0]}"
ALLOWED_IDS_B64="${_B64[1]}"
echo "Channels:    $(printf '%s' "$CHANNELS_B64" | base64 -d)"
echo "Allowed IDs: $(printf '%s' "$ALLOWED_IDS_B64" | base64 -d)"

# ── Stage the Dockerfile and patch ARG defaults ────────────────────────
cp "$EXAMPLE_DIR/agents/hermes/Dockerfile" "$STAGED_DOCKERFILE"
sed -i \
  -e "s|^ARG NEMOCLAW_MESSAGING_CHANNELS_B64=.*|ARG NEMOCLAW_MESSAGING_CHANNELS_B64=$CHANNELS_B64|" \
  -e "s|^ARG NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=.*|ARG NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=$ALLOWED_IDS_B64|" \
  -e "s|^ARG NEMOCLAW_BUILD_ID=.*|ARG NEMOCLAW_BUILD_ID=$(date +%s)|" \
  "$STAGED_DOCKERFILE"

# Phoenix telemetry — flip ENABLE_NEMO_FLOW=1 so the Dockerfile installs
# nemo-flow==0.1.0 from PyPI and applies the Hermes integration patch.
if [[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
  echo "Phoenix endpoint: $PHOENIX_COLLECTOR_ENDPOINT — enabling NeMo-Flow telemetry"
  sed -i \
    -e "s|^ARG ENABLE_NEMO_FLOW=.*|ARG ENABLE_NEMO_FLOW=1|" \
    -e "s|^ARG PHOENIX_COLLECTOR_ENDPOINT=.*|ARG PHOENIX_COLLECTOR_ENDPOINT=$PHOENIX_COLLECTOR_ENDPOINT|" \
    "$STAGED_DOCKERFILE"
fi

# ── Build provider flags from what 02-providers.sh created ─────────────
PROVIDER_FLAGS=(
  --provider "$SANDBOX_NAME-slack-bridge"
  --provider "$SANDBOX_NAME-slack-app"
  --provider "$SANDBOX_NAME-tavily"
  --provider "$SANDBOX_NAME-github"
)

# ── Create the sandbox ─────────────────────────────────────────────────
echo "Creating sandbox $SANDBOX_NAME (OpenShell will build the image)…"
setsid openshell sandbox create \
  --from "$STAGED_DOCKERFILE" \
  --name "$SANDBOX_NAME" \
  --policy "$EXAMPLE_DIR/policy.yaml" \
  "${PROVIDER_FLAGS[@]}" \
  -- env \
    NEMOCLAW_MESSAGING_CHANNELS_B64="$CHANNELS_B64" \
    CHAT_UI_URL="http://127.0.0.1:8642" \
    PHOENIX_COLLECTOR_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-}" \
  nemoclaw-start </dev/null &
CREATE_PID=$!

echo "Waiting for sandbox $SANDBOX_NAME to reach ready…"
READY=0
for _ in {1..180}; do
  if openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" | grep -qi ready; then
    READY=1
    break
  fi
  if ! kill -0 "$CREATE_PID" 2>/dev/null; then
    wait "$CREATE_PID" 2>/dev/null
    echo "openshell sandbox create exited before sandbox reached ready" >&2
    exit 1
  fi
  sleep 2
done

kill -TERM -- -"$CREATE_PID" 2>/dev/null || true
( sleep 2; kill -KILL -- -"$CREATE_PID" 2>/dev/null ) &
SIGKILL_BG_PID=$!
wait "$CREATE_PID" 2>/dev/null || true
kill "$SIGKILL_BG_PID" 2>/dev/null || true
wait "$SIGKILL_BG_PID" 2>/dev/null || true

if [[ "$READY" != "1" ]]; then
  echo "Sandbox did not reach ready in 360s — check 'openshell sandbox logs $SANDBOX_NAME'" >&2
  exit 1
fi
echo "  Sandbox reported ready; detached local create stream."

echo "Re-applying policy via 'openshell policy set --wait' (stage 2)"
openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$SANDBOX_NAME"

echo "Sandbox $SANDBOX_NAME is ready."
