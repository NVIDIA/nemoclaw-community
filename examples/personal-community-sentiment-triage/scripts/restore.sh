#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Re-hydrate a fresh sandbox from a snapshot taken by snapshot.sh.
# Usage:
#   bash scripts/restore.sh                     # use the most recent snapshot
#   bash scripts/restore.sh path/to/snap.tar.gz # use a specific snapshot

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

SNAP_PATH="${1:-$(latest_snapshot)}"
if [[ -z "$SNAP_PATH" || ! -f "$SNAP_PATH" ]]; then
  if [[ -z "${1:-}" ]]; then
    echo "No snapshots found in $SNAPSHOT_DIR — run scripts/snapshot.sh first" >&2
  else
    echo "Snapshot not found: $1" >&2
  fi
  exit 1
fi

assert_sandbox_ready

echo "Restoring from $SNAP_PATH"
echo "Tarball contents (sample):"
# `tar | head` exits with SIGPIPE (141) under `set -o pipefail` once head closes
# stdin, which silently halts the script. `awk` reads to EOF, so no SIGPIPE.
tar tzf "$SNAP_PATH" | awk 'NR<=10 {print "  " $0}'
TOTAL=$(tar tzf "$SNAP_PATH" | wc -l)
echo "  … ($TOTAL files total)"

REMOTE_TMP="/tmp/hermes-snapshot-$$.tar.gz"
echo "Uploading tarball to $REMOTE_TMP …"
# `--no-git-ignore`: `openshell sandbox upload` filters source paths through
# .gitignore by default, and `.snapshots/` is gitignored. Without this flag
# the tarball is silently dropped (upload reports "complete" with 0 bytes).
openshell sandbox upload --no-git-ignore "$SANDBOX_NAME" "$SNAP_PATH" "$REMOTE_TMP"

echo "Extracting into /sandbox/.hermes-data …"
openshell sandbox exec --name "$SANDBOX_NAME" -- \
  bash -c "tar xzf '$REMOTE_TMP' -C /sandbox/.hermes-data && rm -f '$REMOTE_TMP'"

echo "Restore complete. New sessions will see the prior agent state."
