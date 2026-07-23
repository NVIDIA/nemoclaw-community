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
if [[ "$lock_held" == 0 ]]; then
  acquire_review_lock
  trap release_review_lock EXIT INT TERM
fi
assert_sandbox_ready

mkdir -p "$SNAPSHOT_DIR"
chmod 700 "$SNAPSHOT_DIR"
timestamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
nonce="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
name="review-memory-${timestamp}-${nonce}"
remote="/tmp/${name}.tar.gz"
local_archive="$SNAPSHOT_DIR/${name}.tar.gz"

# shellcheck disable=SC2016
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  bash -c '
    set -euo pipefail
    output=$1
    cd /sandbox/.hermes
    find memories -type l -print -quit | grep -q . && {
      echo "Refusing to snapshot symlinked memory state" >&2
      exit 1
    }
    tar -czf "$output" memories
  ' bash "$remote" >/dev/null
run_openshell sandbox download "$NEMOCLAW_SANDBOX_NAME" "$remote" "$local_archive" >/dev/null
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  rm -f "$remote" >/dev/null 2>&1 || true
chmod 600 "$local_archive"
manifest="${local_archive%.tar.gz}.manifest.json"
python3 "$DIR/snapshot-manifest.py" create \
  --archive "$local_archive" \
  --manifest "$manifest" \
  --sandbox "$NEMOCLAW_SANDBOX_NAME" \
  --install-id "$REVIEW_ADVISOR_INSTALL_ID" \
  --repository "$REVIEW_ADVISOR_REPOSITORY" \
  --created-at "$timestamp"
echo "$local_archive"
