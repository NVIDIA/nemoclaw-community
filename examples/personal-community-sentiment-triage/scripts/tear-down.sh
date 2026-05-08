#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Tear down everything brought up by the phase scripts.
#
# Default scope: the per-sandbox state — sandbox itself + the providers
# scoped to it. Host services from 00-host-services.sh (phoenix, token
# manager, postgres, ETLs, postgrest) keep running, since they're
# typically long-lived across multiple bring-ups.
#
# Opt-in flags (mutually exclusive):
#   --stop-host-services    also stop the extras stack (phoenix, token
#                            manager, postgres, ETLs, postgrest); volumes
#                            preserved.
#   --purge-host-services   also stop the extras stack AND remove its
#                            named volumes (token-cache,
#                            source-etls-postgres-data, github-etl-state).
#                            DESTRUCTIVE: requires Outlook re-auth via
#                            authenticate.sh and forces ETL re-scrape.
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
Usage: $(basename "$0") [--stop-host-services | --purge-host-services]

  (no flag)                Delete sandbox and per-sandbox providers only.
                           Host services keep running.
  --stop-host-services     Also stop host services (volumes preserved).
  --purge-host-services    Also stop host services AND remove named volumes.
                           DESTRUCTIVE: requires Outlook re-auth via
                           authenticate.sh and forces ETL re-scrape.

To remove the shared compatible-endpoint inference provider, run
'openshell provider delete compatible-endpoint' directly.
EOF
}

stop_mode=""   # "" | "stop" | "purge"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop-host-services)
      [[ -n "$stop_mode" ]] && { echo "Error: --stop-host-services and --purge-host-services are mutually exclusive" >&2; usage >&2; exit 2; }
      stop_mode="stop"
      ;;
    --purge-host-services)
      [[ -n "$stop_mode" ]] && { echo "Error: --stop-host-services and --purge-host-services are mutually exclusive" >&2; usage >&2; exit 2; }
      stop_mode="purge"
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
openshell provider delete "$SANDBOX_NAME-outlook"      2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-github"       2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-bridge" 2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-app"    2>/dev/null || true

case "$stop_mode" in
  stop)
    echo "Stopping host services (--stop-host-services)"
    bash "$DIR/00-host-services.sh" down
    ;;
  purge)
    echo "Stopping host services and wiping volumes (--purge-host-services)"
    bash "$DIR/00-host-services.sh" down --volumes
    ;;
esac

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
if [[ -z "$stop_mode" ]]; then
  echo "  Host services: still running (re-run with --stop-host-services or --purge-host-services to stop)"
fi
