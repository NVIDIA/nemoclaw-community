#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 1 of 3: Ensure an OpenShell gateway is active.
#
# A gateway is OpenShell's entry point — it runs the L7 proxy, arbitrates
# sandbox traffic, and holds shared state (like provider credentials).
# One gateway can host many sandboxes.
#
# This example uses its own gateway name (default: examples-gateway) on
# port 8090 so it can coexist with `nemoclaw onboard` deployments, which
# use the 'nemoclaw' gateway on port 8080.
#
# OpenShell commands you'll see:
#   - openshell gateway info     — show the active gateway
#   - openshell gateway start    — start a new gateway
#   - openshell gateway select   — make a gateway the active default
#
# Try after this script:
#   $ openshell gateway info

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

if openshell gateway info >/dev/null 2>&1; then
  echo "Gateway already active:"
  openshell gateway info | head -3
  exit 0
fi

echo "No active gateway — starting '$GATEWAY_NAME' on port $GATEWAY_PORT…"
openshell gateway start --name "$GATEWAY_NAME" --port "$GATEWAY_PORT" </dev/null
openshell gateway select "$GATEWAY_NAME"
echo "Gateway active:"
openshell gateway info | head -3
