#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Register the scoped Tool Pack with an existing sandbox. OpenShell stores the
# runtime key on the host and substitutes it at egress; --env names the variable
# without putting its value in argv. Replaces an existing registration.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw  >/dev/null || { echo "nemoclaw not in PATH — install NemoClaw first" >&2; exit 1; }
command -v openshell >/dev/null || { echo "openshell not in PATH — is the gateway installed?" >&2; exit 1; }

require_var MERGE_AH_MCP_TOKEN        "runtime-only key scoped to the Tool Pack and Registered User"
require_var MERGE_AH_TOOL_PACK_ID     "the hr-reader Tool Pack UUID"
require_var MERGE_AH_REGISTERED_USER_ID "the Registered User UUID linked to Workday"

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "error: sandbox '$NEMOCLAW_SANDBOX_NAME' not found." >&2
  echo "Create one first, for example:" >&2
  echo "  nemoclaw onboard --name $NEMOCLAW_SANDBOX_NAME" >&2
  echo "Then re-run this script. This recipe does not create or destroy sandboxes." >&2
  exit 1
fi

MCP_URL="$(ah_mcp_url)"
echo "Sandbox:  $NEMOCLAW_SANDBOX_NAME"
echo "Endpoint: $MCP_URL"

# A query string on the URL is rejected by managed MCP registration. Restrict
# tool access with a dedicated Tool Pack instead.
case "$MCP_URL" in
  *\?*) echo "error: the MCP URL must not carry query parameters" >&2; exit 1 ;;
esac

# Drop a previous registration so the credential key is free. OpenShell requires
# static credential keys to be unique within a sandbox.
if nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp status "$MCP_SERVER_NAME" >/dev/null 2>&1; then
  echo "Existing '$MCP_SERVER_NAME' registration found — replacing it."
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp remove "$MCP_SERVER_NAME" --force || true
  # `mcp remove` detaches but preserves the OpenShell provider; a retained
  # provider blocks re-adding the same server with partial-state recovery.
  run nemoclaw credentials reset "${NEMOCLAW_SANDBOX_NAME}-mcp-${MCP_SERVER_NAME}" --yes || true
fi

# --env names a variable; nemoclaw reads its value from this process's
# environment. The value is never placed in argv.
MERGE_AH_MCP_TOKEN="$MERGE_AH_MCP_TOKEN" \
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp add "$MCP_SERVER_NAME" \
    --url "$MCP_URL" \
    --env MERGE_AH_MCP_TOKEN

echo
echo "Registered '$MCP_SERVER_NAME'. Next: review the registration with nemoclaw $NEMOCLAW_SANDBOX_NAME mcp status $MCP_SERVER_NAME --tools"
