#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Recover the optional host services and Hermes gateway without printing secrets.

set -euo pipefail
AUTOHEAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$AUTOHEAL_DIR/lib.sh"

slack_is_configured() {
  [[ -n "${SLACK_BOT_TOKEN:-}" || -n "${SLACK_APP_TOKEN:-}" ]]
}

expected_slack_policy() {
  local allowed_ids
  allowed_ids="$(normalized_slack_allowed_ids)"
  if [[ -n "$allowed_ids" ]]; then
    printf 'SLACK_ALLOWED_USERS=%s\n' "$allowed_ids"
  else
    printf 'SLACK_ALLOW_ALL_USERS=true\n'
  fi
}

slack_policy_environment_is_exact() {
  local expected="$1" policy_environment="$2"
  local expected_key opposite_key line
  local exact_count=0 expected_key_count=0 opposite_key_count=0
  expected_key="${expected%%=*}"
  case "$expected_key" in
    SLACK_ALLOWED_USERS) opposite_key=SLACK_ALLOW_ALL_USERS ;;
    SLACK_ALLOW_ALL_USERS) opposite_key=SLACK_ALLOWED_USERS ;;
    *) return 1 ;;
  esac

  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    [[ "$line" == "$expected" ]] && exact_count=$((exact_count + 1))
    [[ "$line" == "${expected_key}="* ]] && expected_key_count=$((expected_key_count + 1))
    [[ "$line" == "${opposite_key}="* ]] && opposite_key_count=$((opposite_key_count + 1))
  done <<<"$policy_environment"

  ((exact_count == 1 && expected_key_count == 1 && opposite_key_count == 0))
}

gateway_has_allowlist() {
  local container expected policy_environment
  slack_is_configured || return 0
  container="$(sandbox_container)"
  expected="$(expected_slack_policy)"
  [[ -n "$container" ]] || return 1
  policy_environment="$(docker exec "$container" bash -c '
    pid="$(pgrep -f "[h]ermes gateway run" | head -n1 || true)"
    [ -n "$pid" ] || exit 1
    tr "\0" "\n" < "/proc/$pid/environ" \
      | grep -E "^SLACK_(ALLOWED_USERS|ALLOW_ALL_USERS)=" || true
  ' 2>/dev/null)" || return 1
  slack_policy_environment_is_exact "$expected" "$policy_environment"
}

recent_log_match() {
  local pattern="$1" container logs
  container="$(sandbox_container)"
  [[ -n "$container" ]] || return 1
  logs="$(docker logs --since=15m --tail=5000 "$container" 2>&1 || true)"
  grep -Eiq "$pattern" <<<"$logs"
}

slack_socket_ok() {
  local probe_script
  [[ -n "${SLACK_APP_TOKEN:-}" ]] || return 0
  probe_script='source /sandbox/.hermes-data/.env >/dev/null 2>&1 || source /sandbox/.hermes/.env >/dev/null 2>&1; body="$(curl -sS --max-time 12 -X POST -H "Authorization: Bearer ${SLACK_APP_TOKEN}" https://slack.com/api/apps.connections.open)" || exit 1; printf "%s" "$body" | python3 -c "import json,sys; raise SystemExit(0 if json.load(sys.stdin).get(\"ok\") else 1)"'
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- \
    bash -c "$probe_script" >/dev/null 2>&1
}

outlook_graph_ok() {
  [[ -n "${OUTLOOK_CLIENT_ID:-}" ]] || return 0
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -c \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py --since 1d --top 1 >/dev/null' \
    >/dev/null 2>&1
}

sandbox_exec_runs_as_sandbox() {
  local identity_script
  identity_script='actual_uid="$(id -u)"; sandbox_uid="$(id -u sandbox)"; [ "$actual_uid" -ne 0 ] && [ "$actual_uid" = "$sandbox_uid" ]'
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- \
    sh -c "$identity_script" >/dev/null 2>&1
}

repair_legacy_gateway_ownership() {
  local container="$1"
  docker exec --user root "$container" bash -c '
    set -euo pipefail
    paths=(
      /sandbox/.hermes-data
      /tmp/nemoclaw-start.log
      /tmp/nemoclaw-proxy-env.sh
      /tmp/nemoclaw-autoheal-restart.log
      /tmp/gateway.log
      /tmp/nemo-relay.log
      /tmp/atif-bridge.log
      /tmp/outlook-bridge.log
      /tmp/atif
    )
    for path in "${paths[@]}"; do
      if [[ -e "$path" || -L "$path" ]]; then
        chown --no-dereference --recursive sandbox:sandbox -- "$path"
      fi
    done
  ' >/dev/null 2>&1
}

container_lifecycle_marker() {
  local container="$1"
  docker inspect --format '{{.Id}} {{.RestartCount}} {{.State.StartedAt}}' \
    "$container" 2>/dev/null
}

slack_policy_fingerprint() {
  local expected
  expected="$(expected_slack_policy)"
  python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' \
    "$expected"
}

slack_policy_restart_was_attempted() {
  local file="$AUTOHEAL_STATE_DIR/slack-policy-restart"
  [[ -f "$file" ]] || return 1
  [[ "$(cat "$file")" == "$(slack_policy_fingerprint)" ]]
}

mark_slack_policy_restart_attempted() {
  mkdir -p "$AUTOHEAL_STATE_DIR"
  slack_policy_fingerprint >"$AUTOHEAL_STATE_DIR/slack-policy-restart"
}

clear_slack_policy_restart_attempt() {
  rm -f "$AUTOHEAL_STATE_DIR/slack-policy-restart"
}

restart_gateway() {
  local before_marker container current_container current_marker restart_request
  local gateway_healthy=false restart_observed=false
  container="$(sandbox_container)"
  [[ -n "$container" ]] || return 1
  autoheal_log "requesting a managed restart of ${AUTOHEAL_SANDBOX_NAME}"

  if ! sandbox_exec_runs_as_sandbox; then
    autoheal_log "refusing gateway restart: OpenShell exec is not the sandbox workload user"
    return 1
  fi
  if ! repair_legacy_gateway_ownership "$container"; then
    autoheal_log "gateway restart ownership repair failed"
    return 1
  fi
  if ! before_marker="$(container_lifecycle_marker "$container")"; then
    autoheal_log "could not read the sandbox container lifecycle marker"
    return 1
  fi

  restart_request='actual_uid="$(id -u)"; sandbox_uid="$(id -u sandbox)"; [ "$actual_uid" -ne 0 ] && [ "$actual_uid" = "$sandbox_uid" ] || exit 1; gateway_pid="$(pgrep -f "[h]ermes gateway run" | head -n1 || true)"; [ -n "$gateway_pid" ] || exit 1; kill -TERM "$gateway_pid"'
  if ! openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- \
    sh -c "$restart_request" >/dev/null 2>&1; then
    autoheal_log "restart request disconnected; waiting for the managed supervisor"
  fi

  for _ in $(seq 1 45); do
    current_container="$(sandbox_container)"
    if [[ -n "$current_container" ]] \
      && current_marker="$(container_lifecycle_marker "$current_container")" \
      && [[ "$current_marker" != "$before_marker" ]]; then
      restart_observed=true
      if sandbox_ready && sandbox_gateway_ok; then
        gateway_healthy=true
        if gateway_has_allowlist; then
          clear_slack_policy_restart_attempt
          autoheal_log "Hermes gateway recovered after a managed supervisor restart"
          return 0
        fi
      fi
    fi
    sleep 2
  done
  if [[ "$restart_observed" == true && "$gateway_healthy" == true ]]; then
    if mark_slack_policy_restart_attempted; then
      autoheal_log "gateway recovered with its persisted Slack policy; current .env changes require tear-down and bring-up"
    else
      autoheal_log "gateway recovered, but the stale Slack policy restart could not be recorded"
    fi
    return 1
  fi
  autoheal_log "Hermes gateway did not recover through the managed supervisor within 90 seconds"
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
  mkdir -p "$AUTOHEAL_STATE_DIR"
  exec 9>"$AUTOHEAL_STATE_DIR/watchdog.lock"
  flock -n 9 || return 0

  if proxy_is_configured && ! systemctl --user is-active --quiet nemoclaw-hermes-proxy.service; then
    autoheal_log "starting configured host TLS proxy"
    start_or_restart_unit nemoclaw-hermes-proxy.service || true
  fi

  if ! sandbox_ready; then
    autoheal_log "sandbox ${AUTOHEAL_SANDBOX_NAME} is not Ready; waiting for normal bring-up"
    return 0
  fi

  if sandbox_gateway_failure_confirmed; then
    autoheal_log "sandbox gateway health check failed repeatedly"
    needs_gateway_restart=true
  fi
  if gateway_has_allowlist; then
    clear_slack_policy_restart_attempt
  else
    autoheal_log "Slack gateway allowlist is missing or incorrect"
    if slack_policy_restart_was_attempted; then
      autoheal_log "the managed restart did not restore the current .env Slack policy; run tear-down and bring-up"
    else
      needs_gateway_restart=true
    fi
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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
