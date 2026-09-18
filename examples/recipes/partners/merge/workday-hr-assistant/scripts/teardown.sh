#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove the MCP registration and its OpenShell provider from the sandbox.
#
# Revoke the scoped key in Agent Handler as well — this script cannot do that
# for you, and removing the local registration does not invalidate the key.
# Removal also does not terminate already-open streams; follow NVIDIA's
# lifecycle instructions when immediate termination matters.
#
# This recipe does not create or destroy the sandbox, and leaves the connector's
# application credentials in Agent Handler intact.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || { echo "nemoclaw not in PATH" >&2; exit 1; }

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — nothing to remove."
  exit 0
fi

run nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp remove "$MCP_SERVER_NAME" --force

# `mcp remove` deliberately preserves the provider. Remove it explicitly so a
# later re-registration is not blocked by retained partial state.
run nemoclaw credentials reset "${NEMOCLAW_SANDBOX_NAME}-mcp-${MCP_SERVER_NAME}" --yes

echo
echo "Removed '$MCP_SERVER_NAME' from sandbox '$NEMOCLAW_SANDBOX_NAME'."
echo "Now revoke the scoped runtime key in Agent Handler, then confirm with:"
echo "  EXPECT_REVOKED=1 bash scripts/verify.sh"
