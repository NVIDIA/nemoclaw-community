#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

destroy_sandbox=0
purge_host=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destroy-sandbox) destroy_sandbox=1 ;;
    --purge-host-services) purge_host=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--destroy-sandbox] [--purge-host-services]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

stop_pid_file desk-ui
stop_pid_file mock-rail
if command -v openshell >/dev/null 2>&1 && [[ -f "$EXAMPLE_DIR/.env" ]]; then
  load_env
  openshell forward stop 8642 "$NEMOCLAW_SANDBOX_NAME" >/dev/null 2>&1 || true
fi

if [[ "$destroy_sandbox" == 1 ]]; then
  require_command openshell
  openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null || true
fi
if [[ "$purge_host" == 1 ]]; then
  require_command docker
  docker compose -f "$EXAMPLE_DIR/observability/phoenix-compose.yml" down -v
fi
echo "FinGuard teardown complete."
