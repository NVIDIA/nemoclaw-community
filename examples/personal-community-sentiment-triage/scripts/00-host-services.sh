#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Lifecycle utility for the host-side services in extras/docker-compose.yml.
# These services run on the host (not in the sandbox) and are reached by
# the agent via the L7 proxy. They're modeled as one stack so the user
# only has to learn one compose file.
#
#   phoenix                  — OpenInference trace collector (UI on :6006)
#   ms-graph-token-manager   — Outlook OAuth token broker (host port 8765)
#   postgres                 — backing store for source ETLs
#   github-etl               — pulls GitHub issues/comments into postgres
#   forums-etl               — pulls NVIDIA forum posts into postgres
#   postgrest                — REST API in front of postgres (host port 3100)
#
# Verbs:
#   up                  Start the stack (default if no arg).
#   down                Stop and remove containers, preserve volumes.
#   down --volumes      Also remove named volumes (token-cache,
#                       source-etls-postgres-data, github-etl-state).
#                       DESTRUCTIVE: requires Outlook re-auth and forces
#                       ETL re-scrape on next `up`.
#
# `postgrest` joins the openshell-cluster-* network that OpenShell creates
# when the gateway starts. Default tracks OPENSHELL_GATEWAY (which itself
# defaults to examples-gateway in _lib.sh):
# `${SOURCE_ETL_OPENSHELL_NETWORK:-openshell-cluster-examples-gateway}`. So:
#
#   * If you run `up` before 01-gateway.sh, postgrest is skipped with a
#     notice. Re-run after the gateway is up to bring postgrest in.
#   * If the openshell network is already up, all services come up.
#
# Try after this script:
#   $ docker compose -f extras/docker-compose.yml ps
#   $ curl -s http://localhost:8765/health    # token manager
#   $ curl -s http://localhost:6006           # phoenix UI
#   $ curl -s http://localhost:3100/          # postgrest (after gateway is up)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

COMPOSE_FILE="$EXAMPLE_DIR/extras/docker-compose.yml"
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not in PATH" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [up|down [--volumes]]

  up          Start host services (default if no arg).
  down        Stop and remove containers; preserve named volumes.
  down -v
  down --volumes
              Also remove named volumes (token-cache,
              source-etls-postgres-data, github-etl-state).
              DESTRUCTIVE: requires Outlook re-auth via
              authenticate.sh and forces ETL re-scrape on next up.
EOF
}

cmd_up() {
  load_env

  # Always-on services (no openshell-network dependency).
  SERVICES=(phoenix ms-graph-token-manager postgres github-etl forums-etl)

  # Postgrest needs the openshell-cluster-* network that OpenShell creates
  # when a sandbox is launched on the gateway. Check before including it.
  # Export so the compose file reads the same value as this script's check.
  export SOURCE_ETL_OPENSHELL_NETWORK="${SOURCE_ETL_OPENSHELL_NETWORK:-openshell-cluster-examples-gateway}"
  NETWORK_NAME="$SOURCE_ETL_OPENSHELL_NETWORK"
  if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "openshell network '$NETWORK_NAME' present — including postgrest"
    SERVICES+=(postgrest)
  else
    echo "openshell network '$NETWORK_NAME' not present yet — skipping postgrest."
    echo "  After 01-gateway.sh + sandbox creation, re-run this script to bring postgrest up."
  fi

  echo "Starting host services: ${SERVICES[*]}"
  docker compose -f "$COMPOSE_FILE" up -d --build "${SERVICES[@]}"

  echo
  echo "Status:"
  docker compose -f "$COMPOSE_FILE" ps
}

cmd_down() {
  local with_volumes=0
  case "${1:-}" in
    -v|--volumes) with_volumes=1 ;;
    "") ;;
    *) echo "Unknown flag: $1" >&2; usage >&2; exit 2 ;;
  esac

  if [[ "$with_volumes" == "1" ]]; then
    echo "Stopping host services and REMOVING NAMED VOLUMES."
    echo "  - token-cache (Outlook MSAL sessions — re-run authenticate.sh after next 'up')"
    echo "  - source-etls-postgres-data (mirrored GitHub + forum data — ETLs will re-scrape)"
    echo "  - github-etl-state (ETL cursor)"
    docker compose -f "$COMPOSE_FILE" down -v
  else
    echo "Stopping host services (volumes preserved)."
    docker compose -f "$COMPOSE_FILE" down
  fi
}

case "${1:-up}" in
  up)            shift || true; cmd_up   "$@" ;;
  down)          shift;          cmd_down "$@" ;;
  -h|--help)     usage; exit 0 ;;
  *)             echo "Unknown verb: $1" >&2; usage >&2; exit 2 ;;
esac
