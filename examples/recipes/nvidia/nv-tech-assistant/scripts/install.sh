#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Apply the example's network policies and install the skill into an onboarded
# sandbox. Re-run after changing the skill or policies.

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

echo "Installing nv-tech-assistant into sandbox '$NEMOCLAW_SANDBOX_NAME'"
run nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy-add \
  --from-dir "$EXAMPLE_DIR/policies" \
  --yes
run nemoclaw "$NEMOCLAW_SANDBOX_NAME" skill install \
  "$EXAMPLE_DIR/skills/nv-tech-assistant"

echo
echo "Installed. Ensure the sandbox is running with: bash scripts/start.sh"
