#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGER="$SCRIPT_DIR/../stage-enterprise-cas.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT
SOURCE_DIR="$TEST_ROOT/source"
DEST_DIR="$TEST_ROOT/destination"
mkdir -p "$SOURCE_DIR"

printf '%s\n' root >"$SOURCE_DIR/company-root.crt"
printf '%s\n' trust >"$SOURCE_DIR/company-trust.crt"
printf '%s\n' ignored >"$SOURCE_DIR/unrelated.pem"

output="$(
  NEMOCLAW_ENTERPRISE_CA_SOURCE_DIR="$SOURCE_DIR" \
  NEMOCLAW_ENTERPRISE_CA_DEST_DIR="$DEST_DIR" \
    bash "$STAGER"
)"

[[ "$output" == *"Enterprise CA staging complete (2 updated)."* ]] \
  || fail "expected two enterprise certificates to be staged"
cmp -s "$SOURCE_DIR/company-root.crt" \
  "$DEST_DIR/company-root.crt" \
  || fail "root certificate content changed during staging"
cmp -s "$SOURCE_DIR/company-trust.crt" \
  "$DEST_DIR/company-trust.crt" \
  || fail "trust certificate content changed during staging"
[[ ! -e "$DEST_DIR/unrelated.pem" ]] \
  || fail "unrelated certificate was staged"
permissions="$(stat -c '%a' "$DEST_DIR/company-root.crt" 2>/dev/null \
  || stat -f '%Lp' "$DEST_DIR/company-root.crt")"
[[ "$permissions" == "644" ]] \
  || fail "staged certificate permissions are not 0644"

second_output="$(
  NEMOCLAW_ENTERPRISE_CA_SOURCE_DIR="$SOURCE_DIR" \
  NEMOCLAW_ENTERPRISE_CA_DEST_DIR="$DEST_DIR" \
    bash "$STAGER"
)"
[[ -z "$second_output" ]] || fail "unchanged certificates were staged again"

printf 'PASS: enterprise CA staging\n'
