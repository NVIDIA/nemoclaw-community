#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Forward the financial assistant demo ports from a Brev instance to localhost.

set -Eeuo pipefail

INSTANCE="${1:-financial-assistant-agent}"
UI_PORT="${FINANCE_UI_PORT:-18080}"
PHOENIX_PORT="${FINANCE_PHOENIX_PORT:-6006}"
REPLACE="${FINANCE_REPLACE_FORWARDS:-0}"

log() {
  printf '[finance-forward] %s\n' "$*"
}

die() {
  printf '[finance-forward] ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

check_or_free_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  if [[ "$REPLACE" == "1" ]]; then
    log "stopping existing listener(s) on local port $port"
    kill $pids || true
    sleep 1
    return
  fi
  die "local port $port is already in use. Stop it or rerun with FINANCE_REPLACE_FORWARDS=1."
}

require brev
require ssh
require lsof

log "refreshing Brev SSH config"
brev refresh

check_or_free_port "$UI_PORT"
check_or_free_port "$PHOENIX_PORT"

log "forwarding UI: localhost:$UI_PORT -> $INSTANCE:$UI_PORT"
ssh -f -N -L "$UI_PORT:127.0.0.1:$UI_PORT" "$INSTANCE"

log "forwarding Phoenix: localhost:$PHOENIX_PORT -> $INSTANCE:$PHOENIX_PORT"
ssh -f -N -L "$PHOENIX_PORT:127.0.0.1:$PHOENIX_PORT" "$INSTANCE"

curl -fsS "http://127.0.0.1:$UI_PORT/health" >/dev/null
curl -fsS "http://127.0.0.1:$PHOENIX_PORT/" >/dev/null

cat <<EOF

Forwards are active.

Open:
  UI:      http://127.0.0.1:${UI_PORT}
  Phoenix: http://127.0.0.1:${PHOENIX_PORT}

Check traces:
  curl -sf http://127.0.0.1:${UI_PORT}/api/phoenix/recent | python3 -m json.tool

EOF
