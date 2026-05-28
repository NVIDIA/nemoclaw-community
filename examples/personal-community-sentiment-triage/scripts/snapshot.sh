#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Capture the agent's writable state (/sandbox/.hermes-data — memories, sessions,
# skills, plugins, etc.) to a host-side tarball that survives sandbox deletion.
# A conservative name-based filter excludes obvious credential files before tar.
# Output: $EXAMPLE_DIR/.snapshots/{ts}.tar.gz + .manifest.json. Tarball path is
# echoed on stdout so callers can capture it: SNAP=$(bash scripts/snapshot.sh)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_sandbox_ready

mkdir -p "$SNAPSHOT_DIR"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
TARBALL="$SNAPSHOT_DIR/$TS.tar.gz"
MANIFEST="$SNAPSHOT_DIR/$TS.manifest.json"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading /sandbox/.hermes-data from $SANDBOX_NAME …" >&2
openshell sandbox download "$SANDBOX_NAME" /sandbox/.hermes-data "$WORK/" >/dev/null
STATE_ROOT="$(resolve_download_root "$WORK" .hermes-data)"

filter_credential_files "$STATE_ROOT"

# Tar from inside STATE_ROOT so entries are relative paths — restore.sh can
# extract straight into /sandbox/.hermes-data without --strip-components.
tar czf "$TARBALL" -C "$STATE_ROOT" .

write_snapshot_manifest "$TARBALL" "$MANIFEST" "$TS" "$SANDBOX_NAME" \
  /sandbox/.hermes-data "" "${EXCLUDED_FILES[@]:-}"

TARBALL_SIZE=$(stat -c '%s' "$TARBALL")
FILE_COUNT=$(tar tzf "$TARBALL" | wc -l)
echo "Wrote snapshot: $TARBALL ($FILE_COUNT files, $TARBALL_SIZE bytes)" >&2
echo "Manifest:       $MANIFEST" >&2
# stdout is just the tarball path so callers can `SNAP=$(...)`.
echo "$TARBALL"
