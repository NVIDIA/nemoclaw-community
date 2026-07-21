#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATE_DIR="${EXAMPLE_DIR}/.tmp"

load_env() {
  if [[ ! -f "${EXAMPLE_DIR}/.env" ]]; then
    echo "Missing ${EXAMPLE_DIR}/.env" >&2
    echo "Create it with: cp .env.example .env" >&2
    return 1
  fi
  set -a
  # shellcheck disable=SC1091
  source "${EXAMPLE_DIR}/.env"
  set +a
  export NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-payment-ops}"
  export OPENSHELL_GATEWAY="${OPENSHELL_GATEWAY:-openshell}"
  export OPENSHELL_GATEWAY_ENDPOINT="${OPENSHELL_GATEWAY_ENDPOINT:-https://127.0.0.1:17670}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    return 1
  }
}

stop_pid_file() {
  local name="$1"
  local pid_file="${STATE_DIR}/${name}.pid"
  local pid
  [[ -f "${pid_file}" ]] || return 0
  pid="$(<"${pid_file}")"
  if kill -0 "${pid}" 2>/dev/null; then
    echo "Stopping ${name} (PID ${pid})"
    kill "${pid}"
  fi
  rm -f "${pid_file}"
}

sandbox_phase() {
  local name="${1:-$NEMOCLAW_SANDBOX_NAME}"
  openshell sandbox list 2>/dev/null | awk -v wanted="$name" '
    { gsub(/\033\[[0-9;]*m/, "") }
    NR > 1 && $1 == wanted { print $NF; found = 1; exit }
    END { if (!found) print "Missing" }
  '
}

sandbox_workload_healthy() {
  openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    curl -fsS http://127.0.0.1:4040/healthz >/dev/null 2>&1 \
    && openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      curl -fsS http://127.0.0.1:18642/health >/dev/null 2>&1
}
