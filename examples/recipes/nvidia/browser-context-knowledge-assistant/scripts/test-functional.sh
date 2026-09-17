#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGIN="${1:-http://127.0.0.1:18789}"
SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-ask-nemoclaw}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NEMOHERMES_BIN="${NEMOHERMES_BIN:-$(command -v nemohermes || true)}"

if [[ -z "$NEMOHERMES_BIN" ]]; then
  printf 'ERROR: nemohermes is required for sandbox evidence checks\n' >&2
  exit 1
fi

sandbox_count() {
  local expression="$1"
  "$NEMOHERMES_BIN" "$SANDBOX_NAME" exec -- \
    /opt/hermes/.venv/bin/python -c "$expression" \
    | tail -1
}

SESSION_COUNT_CODE='import sqlite3; from pathlib import Path; p=Path("/sandbox/.hermes/profiles/dashboard-home/state.db"); c=sqlite3.connect(p); print(c.execute("select count(*) from sessions where source = ?", ("ask-nemoclaw-conversation",)).fetchone()[0])'
TRACE_COUNT_CODE='from pathlib import Path; p=Path("/sandbox/.hermes-data/nemo-relay/atif"); print(sum(1 for item in p.rglob("*.json") if item.is_file()))'

before_sessions="$(sandbox_count "$SESSION_COUNT_CODE")"
before_traces="$(sandbox_count "$TRACE_COUNT_CODE")"

"$PYTHON_BIN" "$ROOT/scripts/test-functional.py" "$ORIGIN"

after_sessions="$(sandbox_count "$SESSION_COUNT_CODE")"
after_traces="$(sandbox_count "$TRACE_COUNT_CODE")"

if (( after_sessions < before_sessions + 2 )); then
  printf 'ERROR: Hermes Sessions did not register both functional-test conversations\n' >&2
  exit 1
fi
if (( after_traces <= before_traces )); then
  printf 'ERROR: NeMo Relay did not create a new local ATIF trace\n' >&2
  exit 1
fi

printf 'Hermes Sessions: %d new browser conversations\n' "$((after_sessions - before_sessions))"
printf 'NeMo Relay: %d new local ATIF trace file(s)\n' "$((after_traces - before_traces))"
printf 'End-to-end functional verification completed.\n'
