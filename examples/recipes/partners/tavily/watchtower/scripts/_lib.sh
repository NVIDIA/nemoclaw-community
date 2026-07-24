# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the watchtower scripts. Source this from each script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Auto-source .env if present. Idempotent (set -a + . file), re-sourced on
# every call so vars added to .env after a stale shell export are not missed.
load_env() {
  [[ -f "$EXAMPLE_DIR/.env" ]] || return 0
  echo "Auto-sourcing $EXAMPLE_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  . "$EXAMPLE_DIR/.env"
  set +a
}

# Fail loud if the named variable is unset or empty. Second arg is an
# optional hint appended to the error message.
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

# True if the named sandbox exists on the gateway. Checked via
# `openshell sandbox list --names` (machine-readable, one name per line)
# rather than `nemoclaw <name> status`, whose exit code also reflects
# unrelated status-display failures.
sandbox_exists() {
  command -v openshell >/dev/null || return 1
  openshell sandbox list --names 2>/dev/null | grep -Fxq "$1"
}

load_env

# Shared, overridable knob. onboard.sh exports it for `nemoclaw onboard`;
# install.sh and sweep.sh use it to address the sandbox.
NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-watchtower}"
