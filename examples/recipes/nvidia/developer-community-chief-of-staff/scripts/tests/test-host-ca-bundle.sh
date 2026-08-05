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
trap 'chmod 600 "$TEST_ROOT/unreadable.crt" 2>/dev/null || true; rm -rf "$TEST_ROOT"' EXIT
EXAMPLE_DIR="$TEST_ROOT/example"
HOST_SERVICES="$EXAMPLE_DIR/scripts/00-host-services.sh"
DOCKER_LOG="$TEST_ROOT/docker.log"
export DOCKER_LOG

# Exercise an isolated copy so an ignored real .env cannot override test
# inputs or expose credentials to the test process.
mkdir -p "$EXAMPLE_DIR/scripts" "$EXAMPLE_DIR/extras"
cp "$SOURCE_EXAMPLE_DIR/scripts/_lib.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/00-host-services.sh" \
  "$EXAMPLE_DIR/scripts/"
: >"$EXAMPLE_DIR/extras/docker-compose.yml"

COMPOSE_SOURCE="$SOURCE_EXAMPLE_DIR/extras/docker-compose.yml"
[[ "$(grep -Fc 'create_host_path: false' "$COMPOSE_SOURCE")" == "3" ]] \
  || fail "every host CA bind must reject a missing source path"
grep -Fq '00-host-services.sh up' "$COMPOSE_SOURCE" \
  || fail "Compose usage must route through the host CA preflight"
! grep -Fq 'Usage: docker compose up' "$COMPOSE_SOURCE" \
  || fail "Compose must not advertise a preflight-bypassing startup command"

DOCKERFILE_SOURCE="$SOURCE_EXAMPLE_DIR/agents/hermes/Dockerfile"
first_ca_update="$(grep -n '&& update-ca-certificates' "$DOCKERFILE_SOURCE" | head -1 | cut -d: -f1)"
first_apt_update="$(grep -n '&& apt-get update -qq' "$DOCKERFILE_SOURCE" | head -1 | cut -d: -f1)"
[[ -n "$first_ca_update" && -n "$first_apt_update" && "$first_ca_update" -lt "$first_apt_update" ]] \
  || fail "builder must register copied enterprise CAs before its first apt request"

docker() {
  {
    printf 'bundle=%q args=' "${NEMOCLAW_HOST_CA_BUNDLE:-}"
    printf '%q ' "$@"
    printf '\n'
  } >>"$DOCKER_LOG"
}
export -f docker

expect_rejected() {
  local bundle="$1" expected="$2" output
  : >"$DOCKER_LOG"
  if output="$(NEMOCLAW_HOST_CA_BUNDLE="$bundle" bash "$HOST_SERVICES" up 2>&1)"; then
    fail "invalid CA bundle was accepted: $bundle"
  fi
  assert_contains "$output" "$expected" "invalid CA bundle error"
  [[ ! -s "$DOCKER_LOG" ]] || fail "Docker ran for an invalid CA bundle: $bundle"
}

missing="$TEST_ROOT/missing.crt"
expect_rejected "$missing" \
  "NEMOCLAW_HOST_CA_BUNDLE must be a readable regular file: $missing"
[[ ! -e "$missing" ]] || fail "missing bind source was created"

mkdir "$TEST_ROOT/directory.crt"
expect_rejected "$TEST_ROOT/directory.crt" \
  "NEMOCLAW_HOST_CA_BUNDLE must be a readable regular file: $TEST_ROOT/directory.crt"

expect_rejected relative-ca.crt \
  "NEMOCLAW_HOST_CA_BUNDLE must be an absolute path: relative-ca.crt"

if [[ "$(id -u)" != 0 ]]; then
  : >"$TEST_ROOT/unreadable.crt"
  chmod 000 "$TEST_ROOT/unreadable.crt"
  expect_rejected "$TEST_ROOT/unreadable.crt" \
    "NEMOCLAW_HOST_CA_BUNDLE must be a readable regular file: $TEST_ROOT/unreadable.crt"
fi

readable="$TEST_ROOT/readable.crt"
printf '%s\n' 'test CA bundle' >"$readable"
chmod 600 "$readable"
: >"$DOCKER_LOG"
NEMOCLAW_HOST_CA_BUNDLE="$readable" bash "$HOST_SERVICES" up >/dev/null

assert_contains "$(cat "$DOCKER_LOG")" \
  "bundle=$readable args=compose -f $EXAMPLE_DIR/extras/docker-compose.yml up -d --build" \
  "validated bundle did not reach Compose up"
assert_contains "$(cat "$DOCKER_LOG")" \
  "bundle=$readable args=compose -f $EXAMPLE_DIR/extras/docker-compose.yml ps" \
  "validated bundle did not reach Compose status"

: >"$DOCKER_LOG"
NEMOCLAW_HOST_CA_BUNDLE="$missing" bash "$HOST_SERVICES" down >/dev/null
assert_contains "$(cat "$DOCKER_LOG")" \
  "args=compose -f $EXAMPLE_DIR/extras/docker-compose.yml" \
  "missing bundle blocked host-service teardown"
assert_contains "$(cat "$DOCKER_LOG")" 'down ' \
  "host-service teardown did not reach Compose down"

printf 'PASS: host CA bundle preflight\n'
