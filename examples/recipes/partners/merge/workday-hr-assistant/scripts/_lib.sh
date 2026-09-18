# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the workday-hr-assistant scripts. Source this from each script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MCP_SERVER_NAME="${MCP_SERVER_NAME:-merge-workday}"
AH_BASE_URL="${AH_BASE_URL:-https://ah-api.merge.dev}"
NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-merge-hr}"

# Auto-source .env if present. Idempotent, and re-sourced on every call so a
# variable added to .env after a stale shell export is not missed.
load_env() {
  [[ -f "$EXAMPLE_DIR/.env" ]] || return 0
  echo "Auto-sourcing $EXAMPLE_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  . "$EXAMPLE_DIR/.env"
  set +a
}

# Fail loud if the named variable is unset or empty.
require_var() {
  local name="$1" hint="${2:-}"
  if [[ -z "${!name:-}" ]]; then
    echo "error: $name is not set — set it in $EXAMPLE_DIR/.env${hint:+ ($hint)}" >&2
    exit 1
  fi
}

# Print a command, then run it.
run() {
  echo "+ $*"
  "$@"
}

# True if the named sandbox exists on the gateway.
sandbox_exists() {
  command -v openshell >/dev/null || return 1
  openshell sandbox list --names 2>/dev/null | grep -Fxq "$1"
}

# The scoped Tool Pack MCP endpoint. Built from IDs so the recipe never stores
# a pre-assembled URL that hides which pack and user it binds.
ah_mcp_url() {
  printf '%s/api/v1/tool-packs/%s/registered-users/%s/mcp' \
    "$AH_BASE_URL" "$MERGE_AH_TOOL_PACK_ID" "$MERGE_AH_REGISTERED_USER_ID"
}

load_env
