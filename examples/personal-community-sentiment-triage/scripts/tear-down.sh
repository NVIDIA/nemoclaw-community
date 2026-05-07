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
# Opt-in env flags:
#   DELETE_INFERENCE_PROVIDER=1   also remove the shared `compatible-endpoint`
#                                  provider. Other sandboxes may share it,
#                                  so this is off by default.
#   STOP_HOST_SERVICES=1           also `docker compose down` the extras stack
#                                  (phoenix, token manager, postgres, ETLs,
#                                  postgrest).
#
# Gateway is never destroyed automatically — run
#   $ openshell gateway destroy --name <gateway>
# manually if you want to clean it up too.
#
# OpenShell commands you'll see:
#   - openshell sandbox delete
#   - openshell provider delete

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

echo "Deleting sandbox $SANDBOX_NAME (if present)"
openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true

echo "Deleting per-sandbox providers"
openshell provider delete "$SANDBOX_NAME-outlook"      2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-github"       2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-bridge" 2>/dev/null || true
openshell provider delete "$SANDBOX_NAME-slack-app"    2>/dev/null || true

if [[ "${DELETE_INFERENCE_PROVIDER:-0}" == "1" ]]; then
  echo "Deleting shared inference provider 'compatible-endpoint' (DELETE_INFERENCE_PROVIDER=1)"
  openshell provider delete compatible-endpoint 2>/dev/null || true
fi

if [[ "${STOP_HOST_SERVICES:-0}" == "1" ]]; then
  echo "Stopping host services from extras/docker-compose.yml (STOP_HOST_SERVICES=1)"
  docker compose -f "$EXAMPLE_DIR/extras/docker-compose.yml" down
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
if [[ "${STOP_HOST_SERVICES:-0}" != "1" ]]; then
  echo "  Host services: still running (re-run with STOP_HOST_SERVICES=1 to stop)"
fi
