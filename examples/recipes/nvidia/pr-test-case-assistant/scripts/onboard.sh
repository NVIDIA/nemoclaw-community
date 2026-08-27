#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Create an OpenClaw sandbox with Slack enabled from host-side inputs.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || {
  echo "nemoclaw not in PATH — install it first:" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash" >&2
  exit 1
}

require_var SLACK_BOT_TOKEN "bot user OAuth token beginning with xoxb-"
require_var SLACK_APP_TOKEN "Socket Mode token beginning with xapp-"

NEMOCLAW_PROVIDER="${NEMOCLAW_PROVIDER:-build}"
NEMOCLAW_MODEL="${NEMOCLAW_MODEL:-nvidia/nemotron-3-super-120b-a12b}"

case "$NEMOCLAW_PROVIDER" in
  build)
    require_var NVIDIA_INFERENCE_API_KEY "get a key at https://build.nvidia.com"
    ;;
  custom)
    require_var COMPATIBLE_API_KEY
    require_var NEMOCLAW_ENDPOINT_URL
    ;;
  *)
    echo "note: NemoClaw will validate credentials for provider '$NEMOCLAW_PROVIDER'." >&2
    ;;
esac

if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' already exists — nothing to create."
  echo "Next: bash scripts/install.sh"
  exit 0
fi

export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_PROVIDER
export NEMOCLAW_MODEL
export NEMOCLAW_SANDBOX_NAME
export NEMOCLAW_WEB_SEARCH_PROVIDER=none
export SLACK_BOT_TOKEN
export SLACK_APP_TOKEN
export SLACK_ALLOWED_USERS="${SLACK_ALLOWED_USERS:-}"
export SLACK_ALLOWED_CHANNELS="${SLACK_ALLOWED_CHANNELS:-}"

echo "Onboarding '$NEMOCLAW_SANDBOX_NAME' with Slack Socket Mode"
run nemoclaw onboard \
  --non-interactive \
  --yes \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  --yes-i-accept-third-party-software

echo
echo "Onboarding complete. Next: bash scripts/install.sh"
