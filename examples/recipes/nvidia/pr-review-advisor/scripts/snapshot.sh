#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

scrub_external_secrets
load_env
scrub_external_secrets
require_command openshell
require_command python3
lock_held=0
if [[ "${1:-}" == "--lock-held" ]]; then
  [[ "${REVIEW_ADVISOR_LOCK_DIR:-}" == "${STATE_DIR}/review.lock" \
      && -d "$REVIEW_ADVISOR_LOCK_DIR" ]] || {
    echo "--lock-held requires an inherited active review lock" >&2
    exit 2
  }
  lock_held=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: snapshot.sh" >&2
  exit 2
fi
cleanup_remote=""
cleanup_local_archive=""
cleanup_local_manifest=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$cleanup_remote" ]]; then
    run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      rm -f -- "$cleanup_remote" >/dev/null 2>&1 || true
  fi
  if [[ -n "$cleanup_local_archive" || -n "$cleanup_local_manifest" ]]; then
    rm -f -- "$cleanup_local_archive" "$cleanup_local_manifest" 2>/dev/null || true
  fi
  [[ "$lock_held" == 1 ]] || release_review_lock
  exit "$status"
}
if [[ "$lock_held" == 0 ]]; then
  acquire_review_lock
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
assert_sandbox_ready

mkdir -p "$SNAPSHOT_DIR"
chmod 700 "$SNAPSHOT_DIR"
timestamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
nonce="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
name="review-memory-${timestamp}-${nonce}"
remote="/sandbox/review-staging/${name}.tar.gz"
local_archive="$SNAPSHOT_DIR/${name}.tar.gz"
manifest="${local_archive%.tar.gz}.manifest.json"
[[ ! -e "$local_archive" && ! -L "$local_archive" \
    && ! -e "$manifest" && ! -L "$manifest" ]] || {
  echo "Refusing to overwrite existing local snapshot or manifest path" >&2
  exit 1
}
cleanup_remote="$remote"
cleanup_local_archive="$local_archive"
cleanup_local_manifest="$manifest"

# shellcheck disable=SC2016
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  bash -c '
    set -euo pipefail
    output=$1
    [[ -d /sandbox/review-staging && ! -L /sandbox/review-staging ]] || {
      echo "Snapshot staging directory is missing or unsafe" >&2
      exit 1
    }
    [[ "$output" == /sandbox/review-staging/review-memory-*.tar.gz ]] || {
      echo "Snapshot staging path is outside the expected workspace" >&2
      exit 1
    }
    if [[ -e "$output" || -L "$output" ]]; then
      echo "Refusing to overwrite existing snapshot staging path" >&2
      exit 1
    fi
    cd /sandbox/.hermes
    find memories -type l -print -quit | grep -q . && {
      echo "Refusing to snapshot symlinked memory state" >&2
      exit 1
    }
    tar -czf "$output" memories
  ' bash "$remote" >/dev/null
run_openshell sandbox download \
  "$NEMOCLAW_SANDBOX_NAME" "$remote" "$local_archive" >/dev/null
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  rm -f -- "$remote" >/dev/null
cleanup_remote=""
chmod 600 "$local_archive"
python3 "$DIR/snapshot-manifest.py" create \
  --archive "$local_archive" \
  --manifest "$manifest" \
  --sandbox "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY" \
  --created-at "$timestamp"
cleanup_local_archive=""
cleanup_local_manifest=""
echo "$local_archive"
