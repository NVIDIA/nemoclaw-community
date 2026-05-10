#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Optional host-side observability lifecycle.
#
# Slack, Tavily, and GitHub access happen live from inside the sandbox through
# OpenShell providers and policy. This script is only for optional telemetry.
#
# This script only manages Phoenix telemetry from extras/docker-compose.yml.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

COMPOSE_FILE="$EXAMPLE_DIR/extras/docker-compose.yml"
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not in PATH" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [up|down]

  up      Start optional Phoenix telemetry (default if no arg).
  down    Stop Phoenix.
EOF
}

cmd_up() {
  echo "Starting optional host services: phoenix"
  docker compose -f "$COMPOSE_FILE" up -d --build phoenix
  echo
  docker compose -f "$COMPOSE_FILE" ps
}

cmd_down() {
  echo "Stopping optional host services."
  docker compose -f "$COMPOSE_FILE" down
}

case "${1:-up}" in
  up)        shift || true; cmd_up "$@" ;;
  down)      shift || true; cmd_down "$@" ;;
  -h|--help) usage; exit 0 ;;
  *)         echo "Unknown verb: $1" >&2; usage >&2; exit 2 ;;
esac
