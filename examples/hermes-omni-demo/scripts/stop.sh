#!/usr/bin/env bash
# stop.sh — stop the demo server.
#
# Use this when start.sh is running in the background (tmux, systemd, &).
# If you ran start.sh in the foreground, just hit Ctrl-C.
#
# Usage:
#   bash scripts/stop.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"
if [[ -f "$EXAMPLE_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$EXAMPLE_DIR/.env"
    set +a
fi

PORT="${PORT:-8765}"

PIDS=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -z "$PIDS" ]]; then
    echo "no process listening on port $PORT"
    exit 0
fi

echo "→ stopping process(es) on port $PORT: $PIDS"
kill $PIDS 2>/dev/null || true
sleep 1

# verify gone
if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  process didn't exit cleanly, sending SIGKILL"
    kill -9 $PIDS 2>/dev/null || true
fi

echo "✓ stopped"
