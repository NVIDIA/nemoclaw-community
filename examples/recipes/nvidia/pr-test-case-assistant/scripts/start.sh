#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Recover the sandbox, then wait for Slack Socket Mode readiness.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || {
  echo "nemoclaw not in PATH — run scripts/onboard.sh first" >&2
  exit 1
}

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

run nemoclaw "$NEMOCLAW_SANDBOX_NAME" recover
run nemoclaw "$NEMOCLAW_SANDBOX_NAME" channels status \
  --channel slack \
  --wait \
  --timeout 180 \
  --json

echo
echo "Slack is ready. Send the app a direct message."
