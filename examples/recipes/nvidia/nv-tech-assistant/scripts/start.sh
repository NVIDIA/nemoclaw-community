#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Recover the nv-tech-assistant gateway and host forwards. The NemoClaw
# recover command is safe to run when the gateway is already healthy.

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

echo
echo "Sandbox is ready."
echo "  Interactive shell: nemoclaw $NEMOCLAW_SANDBOX_NAME connect"
echo "  One agent turn:    nemoclaw $NEMOCLAW_SANDBOX_NAME agent --agent main -m '<question>'"
