#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Tear down everything brought up by the phase scripts.
#
# Default scope: the per-sandbox state — sandbox itself + the providers
# scoped to it. Optional host services from 00-host-services.sh (Phoenix)
# keep running unless --stop-host-services is passed.
#
# Opt-in flags:
#   --stop-host-services    also stop the optional Phoenix stack.
#
# Gateway is never destroyed automatically — run
#   $ openshell gateway destroy --name <gateway>
# manually if you want to clean it up too.
#
# To remove the shared compatible-endpoint inference provider, run
#   $ openshell provider delete compatible-endpoint
# directly.
#
# OpenShell commands you'll see:
#   - openshell sandbox delete
#   - openshell provider delete

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--stop-host-services]

  (no flag)                Delete sandbox and per-sandbox providers only.
                           Optional Phoenix keeps running.
  --stop-host-services     Also stop optional Phoenix.

To remove the shared compatible-endpoint inference provider, run
'openshell provider delete compatible-endpoint' directly.
EOF
}

stop_host_services=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop-host-services)
      stop_host_services=1
      ;;
    -h|--help)
      usage; exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2; usage >&2; exit 2
      ;;
  esac
  shift
done

echo "Deleting sandbox $SANDBOX_NAME (if present)"
openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true

echo "Deleting per-sandbox providers"
openshell provider delete "$SANDBOX_NAME-github"       2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-bridge" 2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-app"    2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-tavily"       2>/dev/null || true

if [[ "$stop_host_services" == "1" ]]; then
  echo "Stopping optional host services (--stop-host-services)"
  bash "$DIR/00-host-services.sh" down
fi

# Clean up the staged Dockerfile if a prior bring-up left one behind.
# The bring-up trap normally handles this; this is the belt-and-suspenders
# pass for cases where the script was killed before the trap fired.
if [[ -e "$EXAMPLE_DIR/.Dockerfile.staged" ]]; then
  echo "Removing leftover $EXAMPLE_DIR/.Dockerfile.staged"
  rm -f "$EXAMPLE_DIR/.Dockerfile.staged"
fi

echo
echo "Tear-down complete."
echo "  Gateway:       not destroyed (run 'openshell gateway destroy --name $GATEWAY_NAME' manually)"
if [[ "$stop_host_services" != "1" ]]; then
  echo "  Host services: unchanged (re-run with --stop-host-services to stop Phoenix)"
fi
