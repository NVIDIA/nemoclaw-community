#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX_NAME:-ov-blender-hermes}}"
HOST_IP="${2:-${HOST_IP:-}}"
PROFILE="${BLENDER_HANDOFF_PROFILE:-blenderhandoff}"
RAW_PROFILE="${BLENDER_RAW_PROFILE:-blenderraw}"
GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_ROOT="${DEMO_ROOT:-$HOME/work/ov-blender-hermes-demo}"
INSTALL_ROOT="${BLENDER_WORKFLOW_INSTALL_ROOT:-$HOME/.local/share/nemoclaw-blender}"
HOST_TOOLS="${BLENDER_HOST_TOOLS:-$DEMO_ROOT/venvs/host-tools/bin}"
PID_FILE="$DEMO_ROOT/out/blender-workflow-mcp.pid"
LOG_FILE="$DEMO_ROOT/out/blender-workflow-mcp.log"

if [ -z "$HOST_IP" ]; then
  echo "usage: install_blender_workflow_mcp.sh [sandbox-name] <host-ip>" >&2
  exit 2
fi
for command in curl install nemohermes python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "required command is unavailable: $command" >&2
    exit 1
  fi
done
if [ ! -x "$HOST_TOOLS/uvx" ]; then
  echo "host-tools uvx is unavailable: $HOST_TOOLS/uvx" >&2
  exit 1
fi

mkdir -p "$INSTALL_ROOT" "$DEMO_ROOT/out"
install -m 0755 "$GUIDE_ROOT/scripts/blender_workflow_helper.py" \
  "$INSTALL_ROOT/blender_workflow_helper.py"
install -m 0755 "$GUIDE_ROOT/scripts/blender_workflow_mcp_server.py" \
  "$INSTALL_ROOT/blender_workflow_mcp_server.py"

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE")"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    old_command="$(ps -p "$old_pid" -o args=)"
    if [[ "$old_command" == *blender_workflow_mcp_server.py* ]]; then
      kill "$old_pid"
      sleep 1
    else
      echo "refusing to stop unrelated PID $old_pid from $PID_FILE" >&2
      exit 1
    fi
  fi
fi

BLENDER_WORKFLOW_READ_ROOTS="$DEMO_ROOT" \
BLENDER_WORKFLOW_WRITE_ROOTS="$DEMO_ROOT/out" \
BLENDER_WORKFLOW_HELPER="$INSTALL_ROOT/blender_workflow_helper.py" \
nohup "$HOST_TOOLS/uvx" mcp-proxy --host 0.0.0.0 --port 9878 \
  python3 "$INSTALL_ROOT/blender_workflow_mcp_server.py" \
  >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"
sleep 3
kill -0 "$(cat "$PID_FILE")"
http_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
  http://127.0.0.1:9878/mcp)"
if [ "$http_status" != "406" ]; then
  echo "workflow MCP proxy returned HTTP $http_status instead of 406" >&2
  exit 1
fi

nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/configure_blender_raw_profile.sh" /sandbox/
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/configure_blender_handoff_profile.sh" /sandbox/
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/configure_hermes_blender_mcp.py" /sandbox/
nemohermes "$SANDBOX" exec --timeout 120 -- \
  bash /sandbox/configure_blender_raw_profile.sh "$HOST_IP" "$RAW_PROFILE"
nemohermes "$SANDBOX" exec --timeout 120 -- \
  bash /sandbox/configure_blender_handoff_profile.sh "$HOST_IP" "$PROFILE"
nemohermes "$SANDBOX" exec --timeout 30 -- \
  mkdir -p "/sandbox/.hermes/profiles/$PROFILE/skills/blender-host-sandbox-boundary"
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/skills/blender-host-sandbox-boundary/SKILL.md" \
  "/sandbox/.hermes/profiles/$PROFILE/skills/blender-host-sandbox-boundary/"
nemohermes "$SANDBOX" exec --timeout 30 -- \
  test -f "/sandbox/.hermes/profiles/$PROFILE/skills/blender-host-sandbox-boundary/SKILL.md"

echo "started typed Blender workflow MCP proxy at http://$HOST_IP:9878/mcp"
echo "configured raw Blender profile $RAW_PROFILE in sandbox $SANDBOX"
echo "configured Hermes profile $PROFILE in sandbox $SANDBOX"
