#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Optional host services for the OpenClaw + Omni demo.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"
COMPOSE_FILE="$EXAMPLE_DIR/extras/docker-compose.yml"

usage() {
  cat <<EOF
Usage: $(basename "$0") [up|down]

  up      Start optional Phoenix telemetry (default).
  down    Stop optional Phoenix telemetry.
EOF
}

command -v docker >/dev/null || { echo "docker not in PATH" >&2; exit 1; }
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }

case "${1:-up}" in
  up)
    echo "Starting optional Phoenix telemetry."
    docker compose -f "$COMPOSE_FILE" up -d --build phoenix
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  down)
    echo "Stopping optional Phoenix telemetry."
    docker compose -f "$COMPOSE_FILE" down
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown verb: $1" >&2
    usage >&2
    exit 2
    ;;
esac
