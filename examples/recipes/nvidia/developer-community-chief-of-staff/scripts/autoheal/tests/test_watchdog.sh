#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_eq() {
  local actual="$1" expected="$2" message="$3"
  [[ "$actual" == "$expected" ]] || fail "$message (expected=$expected actual=$actual)"
}

assert_contains() {
  local haystack="$1" needle="$2" message="$3"
  [[ "$haystack" == *"$needle"* ]] || fail "$message (missing: $needle)"
}

assert_array_contains() {
  local needle="$1" message="$2"
  shift 2
  local value
  for value in "$@"; do
    [[ "$value" == "$needle" ]] && return 0
  done
  fail "$message (missing exact argument: $needle)"
}

assert_no_newlines() {
  local context="$1"
  shift
  local value
  for value in "$@"; do
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] \
      || fail "$context contains a newline or carriage return"
  done
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_AUTOHEAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p "$TEST_ROOT/scripts/autoheal" "$TEST_ROOT/home" "$TEST_ROOT/captures"
cp "$SOURCE_AUTOHEAL_DIR/lib.sh" "$TEST_ROOT/scripts/autoheal/lib.sh"
cp "$SOURCE_AUTOHEAL_DIR/watchdog.sh" "$TEST_ROOT/scripts/autoheal/watchdog.sh"
cat >"$TEST_ROOT/scripts/_lib.sh" <<'STUB'
EXAMPLE_DIR=/example
load_env() {
  :
}
STUB

export HOME="$TEST_ROOT/home"
export XDG_STATE_HOME="$TEST_ROOT/state"
export SANDBOX_NAME=hermes-direct
export NEMOCLAW_AUTOHEAL_GATEWAY_HEALTH_ATTEMPTS=0
export NEMOCLAW_AUTOHEAL_GATEWAY_HEALTH_RETRY_SECS=not-a-number

# shellcheck disable=SC1090
source "$TEST_ROOT/scripts/autoheal/watchdog.sh"

[[ ! -e "$AUTOHEAL_STATE_DIR" ]] || fail "sourcing watchdog.sh created the watchdog state or lock"

PROBE_RESULTS=(1 0)
PROBE_COUNT=0
SLEEP_CALLS=()
sandbox_gateway_ok() {
  local result="${PROBE_RESULTS[$PROBE_COUNT]}"
  PROBE_COUNT=$((PROBE_COUNT + 1))
  return "$result"
}
sleep() {
  SLEEP_CALLS+=("$1")
}

if sandbox_gateway_failure_confirmed; then
  fail "a failure followed by success was reported as a confirmed outage"
fi
assert_eq "$PROBE_COUNT" 2 "transient failure probe count"
assert_eq "${#SLEEP_CALLS[@]}" 1 "transient failure sleep count"
assert_eq "${SLEEP_CALLS[0]}" 2 "transient failure retry interval"

PROBE_RESULTS=(1 1 1)
PROBE_COUNT=0
SLEEP_CALLS=()
sandbox_gateway_failure_confirmed || fail "three failed probes were not reported as a confirmed outage"
assert_eq "$PROBE_COUNT" 3 "confirmed failure probe count"
assert_eq "${#SLEEP_CALLS[@]}" 2 "confirmed failure sleep count"
assert_eq "${SLEEP_CALLS[0]}" 2 "first confirmed failure retry interval"
assert_eq "${SLEEP_CALLS[1]}" 2 "second confirmed failure retry interval"

CAPTURE_DIR="$TEST_ROOT/captures"
OPEN_COUNT_FILE="$CAPTURE_DIR/openshell.count"
DOCKER_COUNT_FILE="$CAPTURE_DIR/docker.count"
LIFECYCLE_COUNT_FILE="$CAPTURE_DIR/lifecycle.count"
OPEN_FAIL_FIRST=0
OPEN_FAIL_SECOND=0
DOCKER_FAIL_FIRST=0
LIFECYCLE_FAIL_FIRST=0
LIFECYCLE_STAYS_SAME=0
MOCK_GATEWAY_POLICY_ENV=SLACK_ALLOWED_USERS=U1,U2

reset_captures() {
  rm -f "$CAPTURE_DIR"/openshell.* "$CAPTURE_DIR"/docker.*
  printf '0\n' >"$OPEN_COUNT_FILE"
  printf '0\n' >"$DOCKER_COUNT_FILE"
  printf '0\n' >"$LIFECYCLE_COUNT_FILE"
  OPEN_FAIL_FIRST=0
  OPEN_FAIL_SECOND=0
  DOCKER_FAIL_FIRST=0
  LIFECYCLE_FAIL_FIRST=0
  LIFECYCLE_STAYS_SAME=0
  clear_slack_policy_restart_attempt
}

openshell() {
  local count
  count="$(cat "$OPEN_COUNT_FILE")"
  count=$((count + 1))
  printf '%s\n' "$count" >"$OPEN_COUNT_FILE"
  printf '%s\0' "$@" >"$CAPTURE_DIR/openshell.$count"
  if [[ "$OPEN_FAIL_FIRST" == 1 && "$count" == 1 ]]; then
    return 1
  fi
  if [[ "$OPEN_FAIL_SECOND" == 1 && "$count" == 2 ]]; then
    return 1
  fi
  return 0
}

docker() {
  local count
  count="$(cat "$DOCKER_COUNT_FILE")"
  count=$((count + 1))
  printf '%s\n' "$count" >"$DOCKER_COUNT_FILE"
  printf '%s\0' "$@" >"$CAPTURE_DIR/docker.$count"
  if [[ "$DOCKER_FAIL_FIRST" == 1 && "$count" == 1 ]]; then
    return 1
  fi
  if [[ "$*" == *'SLACK_(ALLOWED_USERS|ALLOW_ALL_USERS)'* ]]; then
    printf '%s\n' "$MOCK_GATEWAY_POLICY_ENV"
  fi
  return 0
}

sandbox_container() {
  printf 'openshell-hermes-direct\n'
}

container_lifecycle_marker() {
  local count
  count="$(cat "$LIFECYCLE_COUNT_FILE")"
  count=$((count + 1))
  printf '%s\n' "$count" >"$LIFECYCLE_COUNT_FILE"
  if [[ "$LIFECYCLE_FAIL_FIRST" == 1 && "$count" == 1 ]]; then
    return 1
  fi
  if [[ "$count" == 1 || "$LIFECYCLE_STAYS_SAME" == 1 ]]; then
    printf 'container-id 0 start-one\n'
  else
    printf 'container-id 1 start-two\n'
  fi
}

sandbox_ready() {
  return 0
}

sandbox_gateway_ok() {
  return 0
}

sleep() {
  :
}

export OUTLOOK_TARGET_MAILBOX='agent mailbox;$(not-executed)'
export OUTLOOK_REPLY_TO='owner+reply@example.test'
export OUTLOOK_ALLOWED_SENDERS='one@example.test, two@example.test'
export SLACK_BOT_TOKEN=secret-bot-sentinel
export SLACK_APP_TOKEN=secret-app-sentinel
export SLACK_ALLOWED_IDS=' U1, U2,, '
export GITHUB_TOKEN=secret-github-sentinel
export MS_GRAPH_ACCESS_TOKEN=secret-graph-sentinel
export ATIF_RELAY_AUTH_TOKEN=secret-atif-sentinel
export AWS_SESSION_TOKEN=secret-aws-sentinel

slack_policy_environment_is_exact \
  'SLACK_ALLOWED_USERS=U1,U2' 'SLACK_ALLOWED_USERS=U1,U2' \
  || fail "one exact Slack allowlist was rejected"
slack_policy_environment_is_exact \
  'SLACK_ALLOW_ALL_USERS=true' 'SLACK_ALLOW_ALL_USERS=true' \
  || fail "one exact Slack allow-all policy was rejected"
if slack_policy_environment_is_exact \
  'SLACK_ALLOWED_USERS=U1,U2' $'SLACK_ALLOWED_USERS=U1,U2\nSLACK_ALLOW_ALL_USERS=true'; then
  fail "Slack policy verification accepted both authorization variables"
fi
if slack_policy_environment_is_exact \
  'SLACK_ALLOWED_USERS=U1,U2' $'SLACK_ALLOWED_USERS=U1,U2\nSLACK_ALLOWED_USERS=U3'; then
  fail "Slack policy verification accepted duplicate allowlist variables"
fi
if slack_policy_environment_is_exact \
  'SLACK_ALLOW_ALL_USERS=true' 'SLACK_ALLOWED_USERS=U1,U2'; then
  fail "Slack policy verification accepted the opposite authorization variable"
fi

mark_slack_policy_restart_attempted
slack_policy_restart_was_attempted \
  || fail "Slack policy restart fingerprint was not recorded"
export SLACK_ALLOWED_IDS=U3
if slack_policy_restart_was_attempted; then
  fail "a changed Slack policy reused an old restart fingerprint"
fi
clear_slack_policy_restart_attempt
export SLACK_ALLOWED_IDS=' U1, U2,, '

reset_captures
slack_socket_ok || fail "Slack Socket Mode probe command failed"
mapfile -d '' -t slack_probe_args <"$CAPTURE_DIR/openshell.1"
assert_no_newlines "Slack Socket Mode OpenShell argv" "${slack_probe_args[@]}"
bash -n -c "${slack_probe_args[${#slack_probe_args[@]} - 1]}" \
  || fail "Slack Socket Mode probe payload is not valid Bash"
assert_contains "${slack_probe_args[${#slack_probe_args[@]} - 1]}" \
  'json.load(sys.stdin)' "Slack Socket Mode response is not parsed from stdin"
if [[ "${slack_probe_args[${#slack_probe_args[@]} - 1]}" == *'json.loads(sys.argv[1])'* ]]; then
  fail "Slack Socket Mode WebSocket ticket is exposed in Python argv"
fi
for argument in "${slack_probe_args[@]}"; do
  [[ "$argument" != *secret-app-sentinel* ]] \
    || fail "the Slack app token was added to probe argv"
done

reset_captures
MOCK_GATEWAY_POLICY_ENV=SLACK_ALLOWED_USERS=U1,U2
restart_gateway || fail "allowlist restart command failed"
assert_eq "$(cat "$OPEN_COUNT_FILE")" 2 "OpenShell preflight and restart call count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 2 "ownership repair and allowlist check call count"
assert_eq "$(cat "$LIFECYCLE_COUNT_FILE")" 2 "container lifecycle marker call count"

mapfile -d '' -t preflight_args <"$CAPTURE_DIR/openshell.1"
assert_no_newlines "workload-user preflight OpenShell argv" "${preflight_args[@]}"
sh -n -c "${preflight_args[${#preflight_args[@]} - 1]}" \
  || fail "workload-user preflight payload is not valid shell"
assert_eq "${preflight_args[0]}" sandbox "preflight command"
assert_eq "${preflight_args[1]}" exec "preflight subcommand"
assert_eq "${preflight_args[2]}" --name "preflight name flag"
assert_eq "${preflight_args[3]}" hermes-direct "preflight sandbox name"
assert_eq "${preflight_args[4]}" -- "preflight command separator"
assert_eq "${preflight_args[5]}" sh "preflight shell"
assert_contains "${preflight_args[7]}" 'actual_uid="$(id -u)"' "preflight did not inspect the effective uid"
assert_contains "${preflight_args[7]}" 'sandbox_uid="$(id -u sandbox)"' "preflight did not resolve the sandbox uid"

mapfile -d '' -t repair_args <"$CAPTURE_DIR/docker.1"
assert_eq "${repair_args[0]}" exec "ownership repair command"
assert_eq "${repair_args[1]}" --user "ownership repair user flag"
assert_eq "${repair_args[2]}" root "ownership repair user"
assert_eq "${repair_args[3]}" openshell-hermes-direct "ownership repair container"
assert_contains "${repair_args[6]}" 'chown --no-dereference --recursive' "ownership repair can follow symbolic links"
assert_contains "${repair_args[6]}" '/sandbox/.hermes-data' "ownership repair omitted writable Hermes state"
assert_contains "${repair_args[6]}" '/tmp/nemoclaw-proxy-env.sh' "ownership repair omitted the proxy environment file"
if grep -Eq '/sandbox/\.hermes([/[:space:]]|$)' <<<"${repair_args[6]}"; then
  fail "ownership repair targets immutable Hermes configuration"
fi

mapfile -d '' -t restart_args <"$CAPTURE_DIR/openshell.2"
assert_no_newlines "gateway restart OpenShell argv" "${restart_args[@]}"
bash -n -c "${restart_args[${#restart_args[@]} - 1]}" \
  || fail "gateway restart payload is not valid Bash"
assert_eq "${restart_args[0]}" sandbox "restart command"
assert_eq "${restart_args[1]}" exec "restart subcommand"
assert_eq "${restart_args[2]}" --name "restart name flag"
assert_eq "${restart_args[3]}" hermes-direct "restart sandbox name"
assert_eq "${restart_args[4]}" -- "restart command separator"
assert_eq "${restart_args[5]}" sh "restart shell"
assert_eq "${restart_args[6]}" -c "restart shell command flag"
assert_contains "${restart_args[${#restart_args[@]} - 1]}" 'actual_uid="$(id -u)"' "restart command omitted its uid precondition"
assert_contains "${restart_args[${#restart_args[@]} - 1]}" 'pgrep -f "[h]ermes gateway run"' "restart command did not find the supervised gateway"
assert_contains "${restart_args[${#restart_args[@]} - 1]}" 'kill -TERM "$gateway_pid"' "restart command did not terminate the supervised gateway"
if [[ "${restart_args[${#restart_args[@]} - 1]}" == *nemoclaw-start* ||
  "${restart_args[${#restart_args[@]} - 1]}" == *nohup* ]]; then
  fail "restart command launched an unmanaged replacement entrypoint"
fi

for argument in "${restart_args[@]}"; do
  case "$argument" in
    OUTLOOK_TARGET_MAILBOX=* | OUTLOOK_REPLY_TO=* | OUTLOOK_ALLOWED_SENDERS=* | SLACK_ALLOWED_USERS=* | SLACK_ALLOW_ALL_USERS=*)
      fail "restart argv attempted to hot-apply persisted sandbox configuration: $argument"
      ;;
  esac
  case "$argument" in
    SLACK_BOT_TOKEN=* | SLACK_APP_TOKEN=* | GITHUB_TOKEN=* | MS_GRAPH_ACCESS_TOKEN=* | ATIF_RELAY_AUTH_TOKEN=* | AWS_SESSION_TOKEN=*)
      fail "a credential name was added to restart argv: $argument"
      ;;
  esac
  for sentinel in secret-bot-sentinel secret-app-sentinel secret-github-sentinel secret-graph-sentinel secret-atif-sentinel secret-aws-sentinel; do
    [[ "$argument" != *"$sentinel"* ]] || fail "a credential value was added to restart argv"
  done
done

mapfile -d '' -t allowlist_check_args <"$CAPTURE_DIR/docker.2"
assert_contains "${allowlist_check_args[4]}" 'SLACK_(ALLOWED_USERS|ALLOW_ALL_USERS)' \
  "gateway verification did not read both Slack policy variables"
assert_contains "${allowlist_check_args[4]}" 'pgrep -f "[h]ermes gateway run"' \
  "gateway verification can match its own probe process"

export SLACK_ALLOWED_IDS=' , , '
MOCK_GATEWAY_POLICY_ENV=SLACK_ALLOW_ALL_USERS=true
reset_captures
restart_gateway || fail "allow-all restart command failed"
assert_eq "$(expected_slack_policy)" SLACK_ALLOW_ALL_USERS=true \
  "empty Slack allowlist did not normalize to allow-all"
mapfile -d '' -t allow_all_args <"$CAPTURE_DIR/openshell.2"
for argument in "${allow_all_args[@]}"; do
  [[ "$argument" != SLACK_ALLOWED_USERS=* && "$argument" != SLACK_ALLOW_ALL_USERS=* ]] \
    || fail "allow-all policy was hot-applied through restart argv"
done
mapfile -d '' -t allow_all_check_args <"$CAPTURE_DIR/docker.2"
assert_contains "${allow_all_check_args[4]}" 'SLACK_(ALLOWED_USERS|ALLOW_ALL_USERS)' \
  "allow-all verification did not read both Slack policy variables"

export SLACK_ALLOWED_IDS=' U1, U2,, '
MOCK_GATEWAY_POLICY_ENV=$'SLACK_ALLOWED_USERS=U1,U2\nSLACK_ALLOW_ALL_USERS=true'
reset_captures
if restart_gateway; then
  fail "managed restart accepted simultaneous allowlist and allow-all policy"
fi
slack_policy_restart_was_attempted \
  || fail "an observed restart with stale policy was not recorded"

MOCK_GATEWAY_POLICY_ENV=SLACK_ALLOWED_USERS=U1,U2
reset_captures
OPEN_FAIL_SECOND=1
restart_gateway \
  || fail "expected OpenShell disconnect prevented supervisor recovery"

reset_captures
OPEN_FAIL_FIRST=1
if restart_gateway; then
  fail "restart continued after a workload-user preflight failure"
fi
assert_eq "$(cat "$OPEN_COUNT_FILE")" 1 "preflight failure OpenShell call count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 0 "preflight failure performed a root repair"
[[ ! -e "$CAPTURE_DIR/openshell.2" ]] || fail "preflight failure reached the restart command"
if slack_policy_restart_was_attempted; then
  fail "preflight failure consumed the one Slack policy restart attempt"
fi

reset_captures
DOCKER_FAIL_FIRST=1
if restart_gateway; then
  fail "restart continued after an ownership repair failure"
fi
assert_eq "$(cat "$OPEN_COUNT_FILE")" 1 "repair failure OpenShell call count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 1 "repair failure Docker call count"
[[ ! -e "$CAPTURE_DIR/openshell.2" ]] || fail "ownership repair failure reached the restart command"
if slack_policy_restart_was_attempted; then
  fail "ownership repair failure consumed the one Slack policy restart attempt"
fi

reset_captures
LIFECYCLE_FAIL_FIRST=1
if restart_gateway; then
  fail "restart continued without a baseline container lifecycle marker"
fi
assert_eq "$(cat "$OPEN_COUNT_FILE")" 1 "lifecycle failure OpenShell call count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 1 "lifecycle failure Docker call count"
[[ ! -e "$CAPTURE_DIR/openshell.2" ]] || fail "lifecycle marker failure reached the restart command"
if slack_policy_restart_was_attempted; then
  fail "lifecycle marker failure consumed the one Slack policy restart attempt"
fi

reset_captures
LIFECYCLE_STAYS_SAME=1
if restart_gateway; then
  fail "restart succeeded without an observed supervisor lifecycle change"
fi
if slack_policy_restart_was_attempted; then
  fail "missing supervisor restart consumed the one Slack policy restart attempt"
fi

printf 'PASS: auto-heal watchdog safety contract\n'
