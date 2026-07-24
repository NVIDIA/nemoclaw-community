#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

lock_held=0
allow_quarantine=0
archive=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock-held) lock_held=1 ;;
    --allow-quarantine) allow_quarantine=1 ;;
    -h|--help)
      echo "Usage: restore.sh [--lock-held] [--allow-quarantine] [review-memory-....tar.gz]"
      exit 0
      ;;
    *)
      [[ -z "$archive" ]] || {
        echo "Usage: restore.sh [--lock-held] [--allow-quarantine] [review-memory-....tar.gz]" >&2
        exit 2
      }
      archive="$1"
      ;;
  esac
  shift
done

scrub_external_secrets
load_env
scrub_external_secrets
owns_lock=0
if [[ "$lock_held" == 1 ]]; then
  [[ "${REVIEW_ADVISOR_LOCK_DIR:-}" == "${STATE_DIR}/review.lock" \
      && -d "$REVIEW_ADVISOR_LOCK_DIR" ]] || {
    echo "--lock-held requires an inherited active review lock" >&2
    exit 2
  }
else
  acquire_review_lock
  owns_lock=1
fi
if [[ "$allow_quarantine" == 1 && "$lock_held" != 1 ]]; then
  echo "--allow-quarantine requires --lock-held" >&2
  exit 2
fi
work=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  [[ -z "$work" ]] || rm -rf "$work"
  [[ "$owns_lock" == 0 ]] || release_review_lock
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -z "$archive" ]]; then
  archive="$(find "$SNAPSHOT_DIR" -maxdepth 1 -type f -name 'review-memory-*.tar.gz' 2>/dev/null | sort | tail -1)"
fi
[[ -n "$archive" && -f "$archive" && ! -L "$archive" ]] || {
  echo "Usage: restore.sh [--lock-held] [--allow-quarantine] [review-memory-....tar.gz]" >&2
  exit 2
}

require_command openshell
require_command python3
if [[ "$allow_quarantine" == 1 ]]; then
  quarantine_record="$(validate_sandbox_quarantine_identity)"
  quarantine_snapshot="$(
    python3 -c 'import json,sys; print(json.loads(sys.argv[1])["recovery_snapshot"])' \
      "$quarantine_record"
  )"
  quarantine_fingerprint="$(
    python3 -c \
      'import json,sys; print(json.loads(sys.argv[1])["active_runtime_fingerprint"])' \
      "$quarantine_record"
  )"
  [[ "$archive" == "$SNAPSHOT_DIR/$quarantine_snapshot" ]] || {
    echo "Quarantine recovery archive does not match the durable marker" >&2
    exit 1
  }
  compute_runtime_fingerprint
  [[ "$REVIEW_ADVISOR_RUNTIME_FINGERPRINT" == "$quarantine_fingerprint" ]] || {
    echo "Quarantine recovery runtime source fingerprint changed" >&2
    exit 1
  }
  assert_sandbox_ready_for_quarantine_recovery
else
  assert_sandbox_ready
fi
work="$(mktemp -d "${TMPDIR:-/tmp}/review-restore.XXXXXXXX")"

manifest="${archive%.tar.gz}.manifest.json"
[[ "$manifest" != "$archive" && -f "$manifest" && ! -L "$manifest" ]] || {
  echo "Snapshot manifest is missing or unsafe: $manifest" >&2
  exit 2
}

python3 "$DIR/snapshot-manifest.py" stage \
  --archive "$archive" \
  --manifest "$manifest" \
  --destination "$work"
staged_archive="$work/$(basename -- "$archive")"
staged_manifest="$work/$(basename -- "$manifest")"
python3 "$DIR/snapshot-manifest.py" validate \
  --archive "$staged_archive" \
  --manifest "$staged_manifest" \
  --sandbox "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY"

remote="/tmp/review-memory-restore-${REVIEW_ADVISOR_INSTALL_ID}.tar.gz"
remote_stage="/tmp/review-memory-restore-${REVIEW_ADVISOR_INSTALL_ID}"
remote_backup="/tmp/review-memory-before-restore-${REVIEW_ADVISOR_INSTALL_ID}.tar.gz"
run_openshell sandbox upload --no-git-ignore \
  "$NEMOCLAW_SANDBOX_NAME" "$staged_archive" "$remote"
# shellcheck disable=SC2016
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  bash -c '
    set -euo pipefail
    archive=$1
    stage=$2
    backup=$3
    home=/sandbox/.hermes
    cleanup() {
      rm -f -- "$archive" "$backup"
      rm -rf -- "$stage"
    }
    trap cleanup EXIT
    rm -rf -- "$stage"
    mkdir -p -- "$stage"
    tar -xzf "$archive" -C "$stage"
    test -d "$stage/memories"
    chmod -R u+rwX,go-rwx "$stage/memories"
    tar -czf "$backup" -C "$home" memories
    restore_ok=1
    rm -rf -- "$home/memories" || restore_ok=0
    if [[ "$restore_ok" == 1 ]]; then
      mv -- "$stage/memories" "$home/memories" || restore_ok=0
    fi
    if [[ "$restore_ok" != 1 ]]; then
      rm -rf -- "$home/memories"
      if ! tar -xzf "$backup" -C "$home"; then
        echo "Memory restore failed and rollback could not be completed" >&2
        exit 1
      fi
      echo "Memory restore failed; previous memory was restored" >&2
      exit 1
    fi
  ' bash "$remote" "$remote_stage" "$remote_backup"
echo "Memory restored. New Hermes sessions will use the restored snapshot."
