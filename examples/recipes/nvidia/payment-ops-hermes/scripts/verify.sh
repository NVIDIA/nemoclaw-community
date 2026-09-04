#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"
load_env

pass() { printf '  [ok] %s\n' "$1"; }
fail() { printf '  [!!] %s\n' "$1" >&2; exit 1; }

python3 "$EXAMPLE_DIR/scripts/smoke-payment.py" >/dev/null && pass "payment screening fixtures" || fail "payment screening fixtures"
curl -fsS http://127.0.0.1:6006 >/dev/null && pass "Phoenix host service" || fail "Phoenix host service"
curl -fsS http://127.0.0.1:8780/released >/dev/null && pass "mock payment rail" || fail "mock payment rail"
curl -fsS http://127.0.0.1:8800 >/dev/null && pass "FinGuard UI" || fail "FinGuard UI"
curl -fsS http://127.0.0.1:8642/health >/dev/null && pass "Hermes host forward" || fail "Hermes host forward"

sandbox_workload_healthy \
  && pass "Hermes 0.20.6 with valid native NeMo Relay 0.7.2 configuration" \
  || fail "Hermes and native NeMo Relay stack"

if openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- curl -fsS --connect-timeout 3 \
  -X POST https://payments-rail.internal/release -d '{"payment_id":"WIRE-1007"}' >/dev/null 2>&1; then
  fail "payment rail unexpectedly reachable from sandbox"
else
  pass "payment rail denied from sandbox"
fi

echo "FinGuard deployment verified."
