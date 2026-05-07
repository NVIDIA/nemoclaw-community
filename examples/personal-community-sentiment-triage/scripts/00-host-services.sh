#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 0 of 3 (host-side): Bring up host services from extras/docker-compose.yml.
#
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
# Most of these come up with no host-side prerequisites. The exception is
# `postgrest`: its compose entry attaches to an external network named
# `${SOURCE_ETL_OPENSHELL_NETWORK:-openshell-cluster-nemoclaw}`, which is
# created by OpenShell when the gateway starts. So:
#
#   * If you run this script before 01-gateway.sh, postgrest is skipped
#     with a notice. Re-run after the gateway is up to bring postgrest in.
#   * If the openshell network is already up, all services come up.
#
# This separation keeps the script idempotent: re-running after step 1
# just adds postgrest, leaving everything else as-is (compose treats
# already-running services as no-ops).
#
# Try after this script:
#   $ docker compose -f extras/docker-compose.yml ps
#   $ curl -s http://localhost:8765/health    # token manager
#   $ curl -s http://localhost:6006           # phoenix UI
#   $ curl -s http://localhost:3100/          # postgrest (after step 1)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

COMPOSE_FILE="$EXAMPLE_DIR/extras/docker-compose.yml"
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not in PATH" >&2; exit 1; }

# Always-on services (no openshell-network dependency).
SERVICES=(phoenix ms-graph-token-manager postgres github-etl forums-etl)

# Postgrest needs the openshell-cluster-* network that OpenShell creates
# when a sandbox is launched on the gateway. Check before including it.
NETWORK_NAME="${SOURCE_ETL_OPENSHELL_NETWORK:-openshell-cluster-nemoclaw}"
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
