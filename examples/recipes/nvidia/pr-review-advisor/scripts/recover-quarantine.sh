#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

[[ $# -eq 0 ]] || {
  echo "Usage: $(basename "$0")" >&2
  exit 2
}

scrub_external_secrets
load_env
scrub_external_secrets
require_command openshell
require_command python3
validate_name "$NEMOCLAW_SANDBOX_NAME"
validate_port "$HERMES_FORWARD_PORT"

acquire_review_lock
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  release_review_lock
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

quarantine="$(sandbox_quarantine_file)"
record="$(validate_sandbox_quarantine_identity)"
session_id="$(
  python3 -c \
    'import json,sys; print(json.loads(sys.argv[1])["requested_session_id"])' \
    "$record"
)"
recorded_fingerprint="$(
  python3 -c \
    'import json,sys; print(json.loads(sys.argv[1])["active_runtime_fingerprint"])' \
    "$record"
)"
snapshot_name="$(
  python3 -c \
    'import json,sys; print(json.loads(sys.argv[1])["recovery_snapshot"])' \
    "$record"
)"
snapshot="$SNAPSHOT_DIR/$snapshot_name"
manifest="${snapshot%.tar.gz}.manifest.json"

python3 "$DIR/sandbox-quarantine.py" validate \
  --marker "$quarantine" \
  --requested-session-id "$session_id" \
  --sandbox-name "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY" \
  --scope-digest "$REVIEW_ADVISOR_SCOPE_DIGEST" \
  --active-runtime-fingerprint "$recorded_fingerprint" \
  --recovery-snapshot "$snapshot_name"
[[ -f "$snapshot" && ! -L "$snapshot" \
    && -f "$manifest" && ! -L "$manifest" ]] || {
  echo "Quarantine recovery snapshot or manifest is missing or unsafe" >&2
  exit 1
}
python3 "$DIR/snapshot-manifest.py" validate \
  --archive "$snapshot" \
  --manifest "$manifest" \
  --sandbox "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY"

compute_runtime_fingerprint
[[ "$REVIEW_ADVISOR_RUNTIME_FINGERPRINT" == "$recorded_fingerprint" ]] || {
  echo "Quarantine recovery requires the exact recorded runtime source" >&2
  exit 1
}

assert_gateway_identity
run_openshell forward stop "$HERMES_FORWARD_PORT" "$NEMOCLAW_SANDBOX_NAME" \
  >/dev/null 2>&1 || true
phase="$(sandbox_phase)"
case "${phase,,}" in
  ready)
    observed="$(
      run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
        cat /opt/review-advisor/runtime-fingerprint
    )"
    [[ "$observed" == "$recorded_fingerprint" ]] || {
      echo "Quarantined sandbox runtime fingerprint does not match the marker" >&2
      exit 1
    }
    ;;
  error|missing)
    ;;
  *)
    echo "Quarantined sandbox is transitioning (phase: $phase); wait and retry" >&2
    exit 1
    ;;
esac

if [[ "${phase,,}" != "missing" ]]; then
  run_openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME"
  for _ in $(seq 1 60); do
    phase="$(sandbox_phase)"
    [[ "$phase" == "Missing" ]] && break
    sleep 1
  done
  phase="$(sandbox_phase)"
  [[ "$phase" == "Missing" ]] || {
    echo "Quarantined sandbox deletion did not complete" >&2
    exit 1
  }
fi

bash "$DIR/03-sandbox.sh" --lock-held --allow-quarantine
observed="$(
  run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    cat /opt/review-advisor/runtime-fingerprint
)"
[[ "$observed" == "$recorded_fingerprint" ]] || {
  echo "Replacement sandbox runtime fingerprint does not match quarantine" >&2
  exit 1
}
bash "$DIR/restore.sh" --lock-held --allow-quarantine "$snapshot"

# The replacement must contain neither mutable review inputs nor the interrupted
# session before the durable quarantine can be cleared.
# shellcheck disable=SC2016
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  bash -c '
    set -euo pipefail
    session=$1
    test -z "$(find /sandbox/review-input -mindepth 1 -maxdepth 1 -print -quit)"
    test -z "$(find /sandbox/review-staging -mindepth 1 -maxdepth 1 -print -quit)"
    /opt/hermes/.venv/bin/python - "$session" <<'"'"'PY'"'"'
import sqlite3
import sys

session_id = sys.argv[1]
connection = sqlite3.connect(
    "file:/sandbox/.hermes/runtime/state.db?mode=ro",
    uri=True,
)
try:
    sessions = connection.execute(
        "SELECT COUNT(*) FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()[0]
    messages = connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
finally:
    connection.close()
if sessions or messages:
    raise SystemExit("interrupted review session survived quarantine recovery")
PY
  ' bash "$session_id"

python3 "$DIR/sandbox-quarantine.py" clear \
  --marker "$quarantine" \
  --requested-session-id "$session_id" \
  --sandbox-name "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY" \
  --scope-digest "$REVIEW_ADVISOR_SCOPE_DIGEST" \
  --active-runtime-fingerprint "$recorded_fingerprint" \
  --recovery-snapshot "$snapshot_name"

if ! rm -f -- "$snapshot" "$manifest"; then
  echo "Sandbox recovered, but the consumed recovery snapshot could not be removed" >&2
  exit 1
fi
echo "Sandbox quarantine recovered by exact replacement; memory restored."
