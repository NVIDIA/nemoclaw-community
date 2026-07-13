#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
require_command openshell

if openshell gateway info --gateway "$OPENSHELL_GATEWAY" >/dev/null 2>&1; then
  openshell gateway select "$OPENSHELL_GATEWAY"
else
  echo "Registering local OpenShell gateway: $OPENSHELL_GATEWAY_ENDPOINT"
  openshell gateway add "$OPENSHELL_GATEWAY_ENDPOINT" --local --name "$OPENSHELL_GATEWAY"
  openshell gateway select "$OPENSHELL_GATEWAY"
fi

openshell status >/dev/null || {
  echo "OpenShell gateway is not reachable. Check: systemctl --user status openshell-gateway" >&2
  exit 1
}
echo "OpenShell gateway ready: $OPENSHELL_GATEWAY"
