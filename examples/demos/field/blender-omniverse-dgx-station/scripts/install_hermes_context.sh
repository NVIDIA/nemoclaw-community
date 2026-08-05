#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX_NAME:-ov-blender-hermes}}"
GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v nemohermes >/dev/null 2>&1 || {
  echo "nemohermes is not on PATH. Use a login shell or add ~/.local/bin to PATH." >&2
  exit 1
}

nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/hermes/blender-host-boundary.md" \
  /sandbox/
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/install_hermes_context.py" \
  /sandbox/
nemohermes "$SANDBOX" exec --timeout 30 -- \
  python /sandbox/install_hermes_context.py

echo "installed the Blender host-boundary SOUL block in sandbox $SANDBOX"
