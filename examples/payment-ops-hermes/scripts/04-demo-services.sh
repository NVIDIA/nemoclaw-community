#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"
load_env
mkdir -p "$STATE_DIR"

stop_pid_file desk-ui
stop_pid_file mock-rail

# Publish the sandbox's Hermes API onto host loopback. OpenShell keeps the
# forward in the background; the UI never connects directly to sandbox IPs.
openshell forward start --background 8642 "$NEMOCLAW_SANDBOX_NAME" \
  >"$STATE_DIR/hermes-forward.log" 2>&1 || true
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8642/health >/dev/null || {
  echo "Hermes host forward did not become healthy on 127.0.0.1:8642" >&2
  cat "$STATE_DIR/hermes-forward.log" >&2 || true
  exit 1
}

python3 "$EXAMPLE_DIR/scripts/mock_payment_rail.py" --port 8780 >"$STATE_DIR/mock-rail.log" 2>&1 &
echo $! >"$STATE_DIR/mock-rail.pid"

HERMES_URL="${HERMES_URL:-http://127.0.0.1:8642}" \
API_SERVER_KEY=nemoclaw-internal \
python3 "$EXAMPLE_DIR/scripts/ui_server.py" --host 0.0.0.0 --port 8800 >"$STATE_DIR/desk-ui.log" 2>&1 &
echo $! >"$STATE_DIR/desk-ui.pid"

for _ in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8780/released >/dev/null 2>&1 && break
  sleep 0.5
done
for _ in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8800 >/dev/null 2>&1 && break
  sleep 0.5
done

echo "FinGuard UI: http://127.0.0.1:8800"
echo "Phoenix:     http://127.0.0.1:6006"
echo "Hermes API:  http://127.0.0.1:8642"
