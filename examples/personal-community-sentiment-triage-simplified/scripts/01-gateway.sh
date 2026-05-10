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

# `openshell gateway start` (v0.0.36) streams gateway logs to stdout and
# stays attached after the gateway is healthy — there's no --detach flag.
# Mirror the 03-sandbox.sh pattern: spawn under setsid (own session/pgrp)
# so we can SIGTERM the whole pgrp on detach — openshell may spawn helper
# processes (ssh, log streamers) that don't get cleaned up otherwise.
# Poll for ready via `openshell gateway info`.
setsid openshell gateway start --name "$GATEWAY_NAME" --port "$GATEWAY_PORT" </dev/null &
GW_START_PID=$!

echo "Waiting for gateway to reach ready…"
READY=0
for _ in {1..90}; do
  if openshell gateway info >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "$GW_START_PID" 2>/dev/null; then
    wait "$GW_START_PID" 2>/dev/null
    echo "openshell gateway start exited before gateway reached ready" >&2
    exit 1
  fi
  sleep 2
done

# Detach: SIGTERM the whole openshell process group (negative PID).
# Catches the openshell CLI plus any helper processes it spawned —
# preventing orphan log streamers from holding the user's terminal
# after the script exits. SIGKILL fallback after 2s caps the worst
# case. `wait` confirms the openshell PID is gone before returning.
# The gateway itself runs as a Docker container and survives.
kill -TERM -- -"$GW_START_PID" 2>/dev/null || true
( sleep 2; kill -KILL -- -"$GW_START_PID" 2>/dev/null ) &
SIGKILL_BG_PID=$!
wait "$GW_START_PID" 2>/dev/null || true
kill "$SIGKILL_BG_PID" 2>/dev/null || true
wait "$SIGKILL_BG_PID" 2>/dev/null || true

if [[ "$READY" != "1" ]]; then
  echo "Gateway did not reach ready in 180s — check 'docker ps' for openshell-cluster-* containers" >&2
  exit 1
fi
echo "  Gateway reported ready; detached local start stream."

openshell gateway select "$GATEWAY_NAME"
echo "Gateway active:"
openshell gateway info | head -3
