#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Shared host-side helpers for the optional auto-heal package.

AUTOHEAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$AUTOHEAL_DIR/.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPTS_DIR/_lib.sh"

load_env

AUTOHEAL_SANDBOX_NAME="${SANDBOX_NAME:-hermes-direct}"
AUTOHEAL_PROXY_UPSTREAM="${NEMOCLAW_HOST_TLS_PROXY_UPSTREAM:-}"
AUTOHEAL_PROXY_PORT="${NEMOCLAW_HOST_TLS_PROXY_PORT:-18080}"
AUTOHEAL_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/nemoclaw-autoheal"
AUTOHEAL_RECREATE_COOLDOWN_SECS="${NEMOCLAW_AUTOHEAL_RECREATE_COOLDOWN_SECS:-900}"

autoheal_log() {
  printf '[nemoclaw-autoheal] %s\n' "$*" >&2
}

proxy_is_configured() {
  [[ -n "$AUTOHEAL_PROXY_UPSTREAM" ]]
}

sandbox_ready() {
  openshell sandbox list 2>/dev/null | grep -E "^[[:space:]]*${AUTOHEAL_SANDBOX_NAME}[[:space:]]" | grep -qi ready
}

sandbox_gateway_ok() {
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc \
    'curl -fsS --max-time 5 http://127.0.0.1:8642/health >/dev/null' >/dev/null 2>&1
}

host_gateway_ok() {
  curl -fsS --max-time 5 http://127.0.0.1:8642/health >/dev/null 2>&1
}

sandbox_container() {
  docker ps --format '{{.Names}}' | grep "^openshell-${AUTOHEAL_SANDBOX_NAME}" | head -n1 || true
}

unit_is_installed() {
  systemctl --user cat "$1" >/dev/null 2>&1
}

start_or_restart_unit() {
  local unit="$1"
  if unit_is_installed "$unit"; then
    systemctl --user restart "$unit"
  else
    autoheal_log "unit is not installed: $unit"
    return 1
  fi
}

state_timestamp() {
  local name="$1"
  local file="$AUTOHEAL_STATE_DIR/$name"
  [[ -f "$file" ]] && cat "$file" || printf '0\n'
}

set_state_timestamp() {
  local name="$1"
  mkdir -p "$AUTOHEAL_STATE_DIR"
  printf '%s\n' "$(date +%s)" >"$AUTOHEAL_STATE_DIR/$name"
}

cooldown_elapsed() {
  local name="$1" cooldown="$2" now last
  now="$(date +%s)"
  last="$(state_timestamp "$name")"
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  (( now - last >= cooldown ))
}
