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
SYSTEMCTL_COUNT_FILE="$CAPTURE_DIR/systemctl.count"
GATEWAY_MARKER_COUNT_FILE="$CAPTURE_DIR/gateway-marker.count"
OPEN_FAIL_FIRST=0
OPEN_FAIL_SECOND=0
DOCKER_FAIL_AT=0
SYSTEMCTL_STOP_FAIL=0
SYSTEMCTL_START_FAIL=0
UNIT_INSTALLED=1
GATEWAY_MARKER_STAYS_SAME=0
MOCK_GATEWAY_POLICY_ENV=SLACK_ALLOWED_USERS=U1,U2
MOCK_CONTAINER_MATCHES=container-id

reset_captures() {
  rm -f "$CAPTURE_DIR"/openshell.* "$CAPTURE_DIR"/docker.* "$CAPTURE_DIR"/systemctl.*
  printf '0\n' >"$OPEN_COUNT_FILE"
  printf '0\n' >"$DOCKER_COUNT_FILE"
  printf '0\n' >"$SYSTEMCTL_COUNT_FILE"
  printf '0\n' >"$GATEWAY_MARKER_COUNT_FILE"
  OPEN_FAIL_FIRST=0
  OPEN_FAIL_SECOND=0
  DOCKER_FAIL_AT=0
  SYSTEMCTL_STOP_FAIL=0
  SYSTEMCTL_START_FAIL=0
  UNIT_INSTALLED=1
  GATEWAY_MARKER_STAYS_SAME=0
  MOCK_CONTAINER_MATCHES=container-id
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
  if [[ "$DOCKER_FAIL_AT" == "$count" ]]; then
    return 1
  fi
  if [[ "${1:-}" == ps ]]; then
    [[ -z "$MOCK_CONTAINER_MATCHES" ]] || printf '%s\n' "$MOCK_CONTAINER_MATCHES"
  fi
  if [[ "$*" == *'SLACK_(ALLOWED_USERS|ALLOW_ALL_USERS)'* ]]; then
    printf '%s\n' "$MOCK_GATEWAY_POLICY_ENV"
  fi
  return 0
}

systemctl() {
  local count
  count="$(cat "$SYSTEMCTL_COUNT_FILE")"
  count=$((count + 1))
  printf '%s\n' "$count" >"$SYSTEMCTL_COUNT_FILE"
  printf '%s\0' "$@" >"$CAPTURE_DIR/systemctl.$count"
  if [[ "$*" == '--user cat nemoclaw-hermes-runtime.service' ]]; then
    [[ "$UNIT_INSTALLED" == 1 ]]
    return
  fi
  if [[ "$*" == '--user stop nemoclaw-hermes-runtime.service' ]]; then
    [[ "$SYSTEMCTL_STOP_FAIL" != 1 ]]
    return
  fi
  if [[ "$*" == '--user start nemoclaw-hermes-runtime.service' ]]; then
    [[ "$SYSTEMCTL_START_FAIL" != 1 ]]
    return
  fi
  return 0
}

# Exercise the production selector before overriding it for the recovery tests.
reset_captures
assert_eq "$(sandbox_container)" container-id "exact-label selector rejected one container"
mapfile -d '' -t selector_args <"$CAPTURE_DIR/docker.1"
assert_array_contains 'label=openshell.ai/managed-by=openshell' \
  "selector omitted the OpenShell managed-by label" "${selector_args[@]}"
assert_array_contains 'label=openshell.ai/sandbox-name=hermes-direct' \
  "selector omitted the exact sandbox-name label" "${selector_args[@]}"
MOCK_CONTAINER_MATCHES=''
if sandbox_container >/dev/null; then
  fail "exact-label selector accepted zero containers"
fi
MOCK_CONTAINER_MATCHES=$'container-one\ncontainer-two'
if sandbox_container >/dev/null; then
  fail "exact-label selector accepted multiple containers"
fi
production_gateway_marker="$(declare -f gateway_process_marker)"
assert_contains "$production_gateway_marker" '/proc/$pid/status' \
  "gateway marker does not read the gateway uid"
assert_contains "$production_gateway_marker" 'id -u sandbox' \
  "gateway marker does not compare the gateway and sandbox uids"

sandbox_container() {
  printf 'container-id\n'
}

gateway_process_marker() {
  local count
  count="$(cat "$GATEWAY_MARKER_COUNT_FILE")"
  count=$((count + 1))
  printf '%s\n' "$count" >"$GATEWAY_MARKER_COUNT_FILE"
  if [[ "$count" == 1 || "$GATEWAY_MARKER_STAYS_SAME" == 1 ]]; then
    printf '101 1000\n'
  else
    printf '202 2000\n'
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
assert_eq "$(cat "$OPEN_COUNT_FILE")" 2 "OpenShell identity probe count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 3 "runtime stop, repair, and policy check count"
assert_eq "$(cat "$SYSTEMCTL_COUNT_FILE")" 3 "runtime unit check, stop, and start count"
assert_eq "$(cat "$GATEWAY_MARKER_COUNT_FILE")" 2 "gateway process marker call count"

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

mapfile -d '' -t stop_args <"$CAPTURE_DIR/docker.1"
assert_eq "${stop_args[0]}" exec "runtime stop command"
assert_eq "${stop_args[1]}" --user "runtime stop user flag"
assert_eq "${stop_args[2]}" root "runtime stop user"
assert_eq "${stop_args[3]}" container-id "runtime stop container"
assert_contains "${stop_args[6]}" 'pkill -TERM -f "$pattern"' \
  "runtime stop does not request graceful termination"
assert_contains "${stop_args[6]}" 'pkill -KILL -f "$pattern"' \
  "runtime stop does not clean up unresponsive legacy processes"
assert_contains "${stop_args[6]}" '"[n]emoclaw-start"' \
  "runtime stop omitted the Hermes entrypoint"
assert_contains "${stop_args[6]}" '"[h]ermes gateway run"' \
  "runtime stop omitted the Hermes gateway"
if [[ "${stop_args[0]}" == restart || "${stop_args[*]}" == *'docker restart'* ]]; then
  fail "recovery still performs a raw Docker restart"
fi

mapfile -d '' -t repair_args <"$CAPTURE_DIR/docker.2"
assert_eq "${repair_args[0]}" exec "ownership repair command"
assert_eq "${repair_args[1]}" --user "ownership repair user flag"
assert_eq "${repair_args[2]}" root "ownership repair user"
assert_eq "${repair_args[3]}" container-id "ownership repair container"
assert_contains "${repair_args[6]}" 'chown --no-dereference --recursive' "ownership repair can follow symbolic links"
assert_contains "${repair_args[6]}" '/sandbox/.hermes-data' "ownership repair omitted writable Hermes state"
assert_contains "${repair_args[6]}" '/tmp/nemoclaw-proxy-env.sh' "ownership repair omitted the proxy environment file"
if grep -Eq '/sandbox/\.hermes([/[:space:]]|$)' <<<"${repair_args[6]}"; then
  fail "ownership repair targets immutable Hermes configuration"
fi

mapfile -d '' -t recovered_preflight_args <"$CAPTURE_DIR/openshell.2"
assert_no_newlines "recovered supervisor identity argv" "${recovered_preflight_args[@]}"
assert_contains "${recovered_preflight_args[${#recovered_preflight_args[@]} - 1]}" \
  'actual_uid="$(id -u)"' "recovered supervisor identity was not checked"

for capture in "$CAPTURE_DIR"/openshell.* "$CAPTURE_DIR"/systemctl.*; do
  mapfile -d '' -t captured_args <"$capture"
  for argument in "${captured_args[@]}"; do
    case "$argument" in
      OUTLOOK_TARGET_MAILBOX=* | OUTLOOK_REPLY_TO=* | OUTLOOK_ALLOWED_SENDERS=* | SLACK_ALLOWED_USERS=* | SLACK_ALLOW_ALL_USERS=*)
        fail "recovery argv attempted to hot-apply persisted sandbox configuration: $argument"
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
done

mapfile -d '' -t allowlist_check_args <"$CAPTURE_DIR/docker.3"
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
mapfile -d '' -t allow_all_check_args <"$CAPTURE_DIR/docker.3"
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
  || fail "transient OpenShell supervisor reconnect prevented recovery"
assert_eq "$(cat "$OPEN_COUNT_FILE")" 3 "transient supervisor reconnect probe count"

reset_captures
OPEN_FAIL_FIRST=1
if restart_gateway; then
  fail "restart continued after a workload-user preflight failure"
fi
assert_eq "$(cat "$OPEN_COUNT_FILE")" 1 "preflight failure OpenShell call count"
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 0 "preflight failure performed a root repair"
assert_eq "$(cat "$SYSTEMCTL_COUNT_FILE")" 0 "preflight failure touched the runtime unit"
if slack_policy_restart_was_attempted; then
  fail "preflight failure consumed the one Slack policy restart attempt"
fi

reset_captures
UNIT_INSTALLED=0
if restart_gateway; then
  fail "restart continued without the runtime launcher unit"
fi
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 0 "missing runtime unit restarted the container"
if slack_policy_restart_was_attempted; then
  fail "missing runtime unit consumed the one Slack policy restart attempt"
fi

reset_captures
DOCKER_FAIL_AT=1
if restart_gateway; then
  fail "restart continued after the runtime process stop failed"
fi
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 1 "runtime stop failure Docker call count"
assert_eq "$(cat "$SYSTEMCTL_COUNT_FILE")" 2 "runtime stop failure systemctl call count"

reset_captures
DOCKER_FAIL_AT=2
if restart_gateway; then
  fail "restart continued after an ownership repair failure"
fi
assert_eq "$(cat "$DOCKER_COUNT_FILE")" 2 "ownership repair failure Docker call count"
assert_eq "$(cat "$SYSTEMCTL_COUNT_FILE")" 2 "ownership repair failure started the runtime unit"

reset_captures
SYSTEMCTL_START_FAIL=1
if restart_gateway; then
  fail "restart succeeded after the runtime launcher failed to start"
fi
assert_eq "$(cat "$SYSTEMCTL_COUNT_FILE")" 3 "runtime start failure systemctl call count"

reset_captures
GATEWAY_MARKER_STAYS_SAME=1
if restart_gateway; then
  fail "restart succeeded without a new gateway process marker"
fi
if slack_policy_restart_was_attempted; then
  fail "missing gateway process restart consumed the Slack policy attempt"
fi

RUNTIME_UNIT_TEMPLATE="$SOURCE_AUTOHEAL_DIR/systemd/nemoclaw-hermes-runtime.service.in"
runtime_unit_text="$(cat "$RUNTIME_UNIT_TEMPLATE")"
assert_contains "$runtime_unit_text" \
  'openshell sandbox exec --name ${SANDBOX_NAME} -- /usr/local/bin/nemoclaw-start' \
  "runtime launcher does not start Hermes through OpenShell"
assert_contains "$runtime_unit_text" \
  "! pgrep -f '[n]emoclaw-start|[h]ermes gateway run'" \
  "runtime launcher has no duplicate-process precondition"
if [[ "$runtime_unit_text" == *'/tmp/nemoclaw-proxy-env.sh'* ]]; then
  fail "runtime launcher sources stale sandbox-owned proxy environment"
fi

printf 'PASS: auto-heal watchdog safety contract\n'
