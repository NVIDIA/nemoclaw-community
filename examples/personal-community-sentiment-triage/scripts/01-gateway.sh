#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Phase 2 of 4 (after 00-host-services.sh): ensure the CLI is pointed at a
# running OpenShell gateway.
#
# OpenShell 0.37+ no longer starts gateways from the CLI. The expected flow is:
#   - install OpenShell with the package-managed installer, which starts the
#     local gateway service for you, or
#   - run the snap-managed gateway service
#   - register that local endpoint with `openshell gateway add`
#
# This script keeps the example aligned to that flow. It selects an existing
# registration when present, or registers the default local endpoint for the
# named gateway when the name is one of the documented install paths.
#
# Try after this script:
#   $ openshell gateway info

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

if openshell gateway info --gateway "$GATEWAY_NAME" >/dev/null 2>&1; then
  echo "Selecting registered gateway '$GATEWAY_NAME'"
  openshell gateway select "$GATEWAY_NAME"
else
  GATEWAY_ENDPOINT="$(default_gateway_endpoint)"
  if [[ -z "$GATEWAY_ENDPOINT" ]]; then
    echo "No registered gateway named '$GATEWAY_NAME' and no default endpoint is known for it." >&2
    echo "Set OPENSHELL_GATEWAY_ENDPOINT in .env, or register the gateway manually with:" >&2
    echo "  openshell gateway add <endpoint> --local --name $GATEWAY_NAME" >&2
    exit 1
  fi

  echo "Registering local gateway '$GATEWAY_NAME' at $GATEWAY_ENDPOINT"
  openshell gateway add "$GATEWAY_ENDPOINT" --local --name "$GATEWAY_NAME"
fi

if ! openshell status >/dev/null 2>&1; then
  echo "OpenShell gateway '$GATEWAY_NAME' is registered but not reachable." >&2
  case "$GATEWAY_NAME" in
    openshell)
      echo "For the package-managed install, verify the user service is running:" >&2
      echo "  systemctl --user status openshell-gateway" >&2
      echo "  systemctl --user restart openshell-gateway" >&2
      ;;
    snap-docker)
      echo "For the snap install, verify the snap service is running and registered:" >&2
      echo "  snap services openshell" >&2
      echo "  openshell gateway add http://127.0.0.1:17670 --local --name snap-docker" >&2
      ;;
  esac
  exit 1
fi

echo "Gateway active:"
openshell gateway info
