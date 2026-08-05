#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Recover the optional host services and Hermes gateway without printing secrets.

set -euo pipefail
AUTOHEAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$AUTOHEAL_DIR/lib.sh"

mkdir -p "$AUTOHEAL_STATE_DIR"
exec 9>"$AUTOHEAL_STATE_DIR/watchdog.lock"
flock -n 9 || exit 0

gateway_has_allowlist() {
  local container expected
  container="$(sandbox_container)"
  expected="${SLACK_ALLOWED_IDS:-}"
  [[ -z "${SLACK_BOT_TOKEN:-}" ]] && return 0
  # An empty configured allowlist intentionally enables Slack's allow-all mode.
  [[ -z "$expected" ]] && return 0
  [[ -n "$container" ]] || return 1
  docker exec "$container" bash -lc '
    pid="$(pgrep -f "hermes gateway run" | head -n1 || true)"
    [ -n "$pid" ] || exit 1
    tr "\0" "\n" < "/proc/$pid/environ" | grep -Fx "SLACK_ALLOWED_USERS='"$expected"'"
  ' >/dev/null 2>&1
}

recent_log_match() {
  local pattern="$1" container logs
  container="$(sandbox_container)"
  [[ -n "$container" ]] || return 1
  logs="$(docker logs --since=15m --tail=5000 "$container" 2>&1 || true)"
  grep -Eiq "$pattern" <<<"$logs"
}

slack_socket_ok() {
  [[ -n "${SLACK_APP_TOKEN:-}" ]] || return 0
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc '
    source /sandbox/.hermes-data/.env >/dev/null 2>&1 || source /sandbox/.hermes/.env >/dev/null 2>&1
    body="$(curl -sS --max-time 12 -X POST -H "Authorization: Bearer ${SLACK_APP_TOKEN}" https://slack.com/api/apps.connections.open)" || exit 1
    python3 -c "import json,sys; raise SystemExit(0 if json.loads(sys.argv[1]).get(\"ok\") else 1)" "$body"
  ' >/dev/null 2>&1
}

outlook_graph_ok() {
  [[ -n "${OUTLOOK_CLIENT_ID:-}" ]] || return 0
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py --since 1d --top 1 >/dev/null' \
    >/dev/null 2>&1
}

restart_gateway() {
  local container
  container="$(sandbox_container)"
  [[ -n "$container" ]] || return 1
  autoheal_log "restarting Hermes gateway in ${AUTOHEAL_SANDBOX_NAME}"
  docker exec "$container" bash -lc '
    set +e
    pkill -f "[h]ermes gateway run" 2>/dev/null
    pkill -f "[s]ocat TCP-LISTEN:8642" 2>/dev/null
    pkill -f "[n]emo-relay --bind" 2>/dev/null
    pkill -f "[o]utlook-bridge.py" 2>/dev/null
    sleep 2
    nohup /usr/local/bin/nemoclaw-start >/tmp/nemoclaw-autoheal-restart.log 2>&1 < /dev/null &
  ' >/dev/null

  for _ in $(seq 1 45); do
    if sandbox_gateway_ok && gateway_has_allowlist; then
      autoheal_log "Hermes gateway recovered"
      return 0
    fi
    sleep 2
  done
  autoheal_log "Hermes gateway did not recover within 90 seconds"
  return 1
}

recreate_sandbox() {
  if ! cooldown_elapsed sandbox-recreate "$AUTOHEAL_RECREATE_COOLDOWN_SECS"; then
    autoheal_log "sandbox recreation cooldown is active"
    return 0
  fi
  autoheal_log "recreating ${AUTOHEAL_SANDBOX_NAME} after a confirmed sandbox egress failure"
  set_state_timestamp sandbox-recreate
  (
    cd "$EXAMPLE_DIR"
    openshell sandbox delete "$AUTOHEAL_SANDBOX_NAME" >/dev/null 2>&1 || true
    SANDBOX_READY_TIMEOUT_SECS=900 bash scripts/03-sandbox.sh
  )
}

main() {
  local needs_gateway_restart=false

  if proxy_is_configured && ! systemctl --user is-active --quiet nemoclaw-hermes-proxy.service; then
    autoheal_log "starting configured host TLS proxy"
    start_or_restart_unit nemoclaw-hermes-proxy.service || true
  fi

  if ! sandbox_ready; then
    autoheal_log "sandbox ${AUTOHEAL_SANDBOX_NAME} is not Ready; waiting for normal bring-up"
    return 0
  fi

  if ! sandbox_gateway_ok; then
    autoheal_log "sandbox gateway health check failed"
    needs_gateway_restart=true
  fi
  if ! gateway_has_allowlist; then
    autoheal_log "Slack gateway allowlist is missing or incorrect"
    needs_gateway_restart=true
  fi

  if recent_log_match 'ServerDisconnectedError|Server disconnected|NET:FAIL.*(slack\.com:443|apps\.connections\.open)|(slack\.com:443|apps\.connections\.open).*NET:FAIL'; then
    if slack_socket_ok; then
      autoheal_log "Slack gateway failure detected; Socket Mode is reachable"
      needs_gateway_restart=true
    else
      recreate_sandbox
      needs_gateway_restart=false
    fi
  fi

  if recent_log_match 'NET:FAIL.*graph\.microsoft\.com:443|graph\.microsoft\.com:443.*NET:FAIL|Remote end closed connection without response'; then
    if outlook_graph_ok; then
      autoheal_log "Outlook bridge failure detected; Graph is reachable"
      needs_gateway_restart=true
    else
      recreate_sandbox
      needs_gateway_restart=false
    fi
  fi

  if "$needs_gateway_restart"; then
    restart_gateway || true
  fi

  if ! host_gateway_ok && sandbox_gateway_ok; then
    autoheal_log "restoring the host gateway forward"
    start_or_restart_unit nemoclaw-hermes-gateway-forward.service || true
  fi
}

main "$@"
