# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the shrike-security scripts. Source this from each script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Auto-source .env if present. Idempotent (set -a + . file), re-sourced on
# every call so a var added to .env after a stale shell export is not missed.
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

# Upsert a provider instance from an imported profile, supplying the credential
# value via a clean sub-environment (env -i) so openshell stores exactly the
# value we pass — not whatever leaks in from the parent shell. Mirrors the
# convention in the nvidia recipes. `provider update` cannot change a
# provider's type, so drop-and-recreate on a type mismatch.
#
# Usage: upsert_cred <provider-name> <profile-id> KEY="$VALUE"
upsert_cred() {
  local pname="$1" ptype="$2"
  shift 2
  local env_args=() cred_args=() pair
  for pair in "$@"; do
    env_args+=("$pair")
    cred_args+=(--credential "${pair%%=*}")
  done
  if openshell provider get "$pname" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider update "$pname" "${cred_args[@]}"
  else
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider create --name "$pname" --type "$ptype" "${cred_args[@]}"
  fi
}

# Shared, overridable knobs.
#   NEMOCLAW_SANDBOX_NAME     — sandbox onboard/install/verify address.
#   SHRIKE_PROFILE_ID         — v2 provider-profile id (providers/shrike.yaml).
#   SHRIKE_PROVIDER_NAME      — provider instance created from that profile.
# The provider holds the Shrike key on the gateway; the sandbox env carries
# only the placeholder `openshell:resolve:env:SHRIKE_API_KEY`, substituted by
# the L7 proxy on egress. The real key never enters the sandbox.
NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-shrike-security}"
SHRIKE_PROFILE_ID="${SHRIKE_PROFILE_ID:-nemoclaw-shrike}"
SHRIKE_PROVIDER_NAME="${SHRIKE_PROVIDER_NAME:-${NEMOCLAW_SANDBOX_NAME}-shrike}"
