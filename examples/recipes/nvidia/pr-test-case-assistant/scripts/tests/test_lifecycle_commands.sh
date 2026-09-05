#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1" needle="$2" message="$3"
  [[ "$haystack" == *"$needle"* ]] || fail "$message (missing: $needle)"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_EXAMPLE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT
EXAMPLE_DIR="$TEST_ROOT/example"
COMMAND_LOG="$TEST_ROOT/commands.log"
export COMMAND_LOG

mkdir -p "$EXAMPLE_DIR/scripts" "$EXAMPLE_DIR/policies" \
  "$EXAMPLE_DIR/skills/pr-test-case-assistant"
cp "$SOURCE_EXAMPLE_DIR/scripts/_lib.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/onboard.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/install.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/start.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/stop.sh" \
  "$EXAMPLE_DIR/scripts/"

nemoclaw() {
  {
    printf 'sandbox=%q args=' "${NEMOCLAW_SANDBOX_NAME:-}"
    printf '%q ' "$@"
    printf '\n'
  } >>"$COMMAND_LOG"
}
export -f nemoclaw

openshell() {
  if [[ "$*" == "sandbox list --names" && "${FAKE_SANDBOX_EXISTS:-0}" == "1" ]]; then
    printf '%s\n' "${NEMOCLAW_SANDBOX_NAME:-pr-test-case-assistant}"
  fi
}
export -f openshell

export NEMOCLAW_SANDBOX_NAME=pr-test-case-assistant

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=pr-test-case-assistant policy-add --from-dir $EXAMPLE_DIR/policies --yes" \
  "install did not apply the policy directory"
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=pr-test-case-assistant skill install $EXAMPLE_DIR/skills/pr-test-case-assistant" \
  "install did not deploy the assistant skill"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/start.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=pr-test-case-assistant recover" \
  "start did not recover the selected sandbox"
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=pr-test-case-assistant channels status --channel slack --wait --timeout 180 --json" \
  "start did not wait for Slack readiness"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/stop.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "sandbox=pr-test-case-assistant args=tunnel stop" \
  "stop did not target the selected sandbox"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=0 \
  NVIDIA_INFERENCE_API_KEY=test-key \
  SLACK_BOT_TOKEN=xoxb-test \
  SLACK_APP_TOKEN=xapp-test \
  bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=onboard --non-interactive --yes --name pr-test-case-assistant --yes-i-accept-third-party-software" \
  "onboard did not use the documented non-interactive command"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=0 bash "$EXAMPLE_DIR/scripts/stop.sh" >/dev/null
[[ ! -s "$COMMAND_LOG" ]] || fail "stop called NemoClaw for a missing sandbox"

printf 'PASS: pr-test-case-assistant lifecycle command contracts\n'
