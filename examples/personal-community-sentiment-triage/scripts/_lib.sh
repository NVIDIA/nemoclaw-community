# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the phase scripts. Source this from each phase script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Shared, overridable knobs.
SANDBOX_NAME="${SANDBOX_NAME:-hermes-direct}"
GATEWAY_NAME="${OPENSHELL_GATEWAY:-examples-gateway}"
GATEWAY_PORT="${OPENSHELL_GATEWAY_PORT:-8090}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-$EXAMPLE_DIR/.snapshots}"

# Find the most recent snapshot tarball, or print nothing if none exist.
# Used by restore.sh when the caller doesn't pass an explicit path.
latest_snapshot() {
  [[ -d "$SNAPSHOT_DIR" ]] || return 0
  ls -1t "$SNAPSHOT_DIR"/*.tar.gz 2>/dev/null | head -1
}

# Auto-source .env if present and key vars are missing. Called by every
# phase script that needs credentials, so a developer can run any one of
# them directly without `set -a && source .env` in the shell first.
load_env() {
  if [[ -f "$EXAMPLE_DIR/.env" && -z "${OUTLOOK_SESSION_UUID:-}" ]]; then
    echo "Auto-sourcing $EXAMPLE_DIR/.env (vars not present in shell)"
    set -a
    # shellcheck disable=SC1091
    . "$EXAMPLE_DIR/.env"
    set +a
  fi
}

# Detect the host address reachable from inside Docker containers. On Linux
# this is the bridge gateway (typically 172.17.0.1); on Docker Desktop it's
# host.docker.internal. Mirrors NemoClaw's detectContainerHostAddress() at
# src/lib/onboard.ts:132 so the example behaves consistently with the
# `nemoclaw onboard` flow under L7-proxy enforcement.
detect_token_manager_host() {
  if [[ -n "${TOKEN_MANAGER_HOST:-}" ]]; then
    echo "$TOKEN_MANAGER_HOST"; return
  fi
  local gw
  gw=$(docker network inspect bridge --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)
  if [[ -n "$gw" && "$gw" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "$gw"
  else
    echo "host.docker.internal"
  fi
}

# Upsert a single credential on a provider. Uses `env -i` to build a clean
# sub-environment, so the value openshell stores is the one we explicitly
# pass — not whatever is leaking in from the parent shell. Without this,
# `openshell provider update --credential X` silently picks up an empty
# value when the caller forgets to `set -a && source .env` first, breaking
# placeholder substitution at the L7 proxy at sandbox-start time.
upsert_cred() {
  local pname="$1" ptype="$2" envkey="$3" value="$4"
  if [[ -z "$value" ]]; then
    echo "  skip $pname.$envkey (no value)"
    return 0
  fi
  if openshell provider get "$pname" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" "$envkey=$value" \
      openshell provider update "$pname" --credential "$envkey"
  else
    env -i HOME="$HOME" PATH="$PATH" "$envkey=$value" \
      openshell provider create --name "$pname" --type "$ptype" --credential "$envkey"
  fi
}
