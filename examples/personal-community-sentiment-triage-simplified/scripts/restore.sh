#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Re-hydrate a fresh sandbox from a snapshot taken by snapshot.sh.
#
# Usage:
#   bash scripts/restore.sh                     # use the most recent snapshot
#   bash scripts/restore.sh path/to/snap.tar.gz # use a specific snapshot
#
# Hermes reads its state directories lazily on first access per session, so
# restoring AFTER bring-up.sh is fine — no agent restart is required. New
# sessions started after restore will see the prior memories, skills, and
# session history.
#
# OpenShell commands you'll see:
#   - openshell sandbox upload <name> <local> <dest>
#   - openshell sandbox exec   <name> -- <command>

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

SNAP_PATH="${1:-$(latest_snapshot)}"
if [[ -z "$SNAP_PATH" || ! -f "$SNAP_PATH" ]]; then
  if [[ -z "${1:-}" ]]; then
    echo "No snapshots found in $SNAPSHOT_DIR — run scripts/snapshot.sh first" >&2
  else
    echo "Snapshot not found: $1" >&2
  fi
  exit 1
fi

# Validate the sandbox is up — restoring into a non-existent sandbox would
# silently land in a tmpfs and disappear.
if ! openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" | grep -qi ready; then
  echo "Sandbox $SANDBOX_NAME is not ready — bring it up first (scripts/bring-up.sh)" >&2
  exit 1
fi

echo "Restoring from $SNAP_PATH"
echo "Tarball contents (sample):"
tar tzf "$SNAP_PATH" | head -10 | sed 's/^/  /'
TOTAL=$(tar tzf "$SNAP_PATH" | wc -l)
echo "  … ($TOTAL files total)"

# Upload the tarball into the sandbox, extract over .hermes-data, then
# delete the staging file. Using upload (rather than exec piping stdin)
# keeps the path explicit and the failure modes obvious.
REMOTE_TMP="/tmp/hermes-snapshot-$$.tar.gz"
echo "Uploading tarball to $REMOTE_TMP …"
openshell sandbox upload "$SANDBOX_NAME" "$SNAP_PATH" "$REMOTE_TMP"

echo "Extracting into /sandbox/.hermes-data …"
openshell sandbox exec "$SANDBOX_NAME" -- \
  bash -c "tar xzf '$REMOTE_TMP' -C /sandbox/.hermes-data && rm -f '$REMOTE_TMP'"

echo "Restore complete. New sessions will see the prior agent state."
