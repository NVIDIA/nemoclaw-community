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

# Exercise an isolated copy so a developer's ignored .env cannot affect the
# command contract test or expose real credentials to the test process.
mkdir -p "$EXAMPLE_DIR/scripts" "$EXAMPLE_DIR/policies" \
  "$EXAMPLE_DIR/skills/nv-tech-assistant"
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
    printf '%s\n' "${NEMOCLAW_SANDBOX_NAME:-nv-tech-assistant}"
  fi
}
export -f openshell

export NEMOCLAW_SANDBOX_NAME=nv-tech-assistant

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/start.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "sandbox=nv-tech-assistant args=nv-tech-assistant recover" \
  "start did not use the sandbox-scoped recover command"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/stop.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "sandbox=nv-tech-assistant args=tunnel stop" \
  "stop did not target the selected sandbox through tunnel stop"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=nv-tech-assistant policy-add --from-dir $EXAMPLE_DIR/policies --yes" \
  "install did not apply the example policy directory"
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=nv-tech-assistant skill install $EXAMPLE_DIR/skills/nv-tech-assistant" \
  "install did not deploy the example skill"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=0 NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=onboard --non-interactive --yes --name nv-tech-assistant --yes-i-accept-third-party-software" \
  "onboard did not use the documented non-interactive command"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=0 bash "$EXAMPLE_DIR/scripts/stop.sh" >/dev/null
[[ ! -s "$COMMAND_LOG" ]] || fail "stop called NemoClaw for a missing sandbox"

printf 'PASS: nv-tech-assistant lifecycle command contracts\n'
