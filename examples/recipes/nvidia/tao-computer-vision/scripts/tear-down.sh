#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Tear down the TAO recipe. Safe default: stop the host tao MCP server only.
# --destroy-sandbox also removes the NemoClaw sandbox. The host workspace
# (datasets, checkpoints, results) is never deleted.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
cd "$ROOT"
[ -f .env ] && { set -a; . ./.env; set +a; }

SANDBOX="${TAO_SANDBOX:-tao}"
WORKSPACE="${TAO_WORKSPACE:-$HOME/tao-workspace}"
PORT=9901
DESTROY=0
for arg in "$@"; do [ "$arg" = "--destroy-sandbox" ] && DESTROY=1; done

# Stop the MCP server by its listening port (never matches this script).
SPID=$(ss -tlnp 2>/dev/null | grep ":$PORT" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
if [ -n "${SPID:-}" ]; then
  kill "$SPID" 2>/dev/null && echo "stopped tao MCP server (pid $SPID)"
else
  echo "no tao MCP server was running on :$PORT"
fi

if [ "$DESTROY" -eq 1 ]; then
  nemoclaw "$SANDBOX" destroy --yes 2>/dev/null && echo "destroyed sandbox '$SANDBOX'" \
    || echo "could not destroy sandbox '$SANDBOX' (already gone?)"
fi

echo "workspace kept at: $WORKSPACE  (remove manually when no longer needed)"
