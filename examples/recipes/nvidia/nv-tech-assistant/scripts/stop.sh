#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Stop the nv-tech-assistant gateway and host auxiliary services without
# deleting the sandbox, workspace, or credentials. Recover them later with
# scripts/start.sh.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || {
  echo "nemoclaw not in PATH" >&2
  exit 1
}

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — nothing to stop."
  exit 0
fi

export NEMOCLAW_SANDBOX_NAME
run nemoclaw tunnel stop

echo
echo "Gateway and host auxiliary services stopped without deleting sandbox state."
echo "Restart with: bash scripts/start.sh"
