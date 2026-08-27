# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# shellcheck shell=bash

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_env() {
  [[ -f "$EXAMPLE_DIR/.env" ]] || return 0
  echo "Auto-sourcing $EXAMPLE_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  . "$EXAMPLE_DIR/.env"
  set +a
}

require_var() {
  local name="$1" hint="${2:-}"
  if [[ -z "${!name:-}" ]]; then
    echo "error: $name is not set in $EXAMPLE_DIR/.env${hint:+ ($hint)}" >&2
    exit 1
  fi
}

run() {
  echo "+ $*"
  "$@"
}

sandbox_exists() {
  command -v openshell >/dev/null || return 1
  openshell sandbox list --names 2>/dev/null | grep -Fxq "$1"
}

load_env

NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-pr-test-case-assistant}"
