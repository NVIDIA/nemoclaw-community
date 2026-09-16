#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Pull locally stored ATIF trajectories written by NeMo Relay off the running
# sandbox into a host-side tarball. /sandbox/atif is ephemeral — capture before
# tear-down to keep local exports or remote-delivery recovery copies. An empty
# directory still produces a tarball; the manifest explains why it may be empty.
# Output: $EXAMPLE_DIR/.traces/atif-{ts}.tar.gz + .manifest.json. Tarball path
# is echoed on stdout: TRACE=$(bash scripts/download-traces.sh)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_sandbox_ready

TRACES_DIR="${TRACES_DIR:-$EXAMPLE_DIR/.traces}"
mkdir -p "$TRACES_DIR"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
TARBALL="$TRACES_DIR/atif-$TS.tar.gz"
MANIFEST="$TRACES_DIR/atif-$TS.manifest.json"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading /sandbox/atif from $SANDBOX_NAME …" >&2
openshell sandbox download "$SANDBOX_NAME" /sandbox/atif "$WORK/" >/dev/null
TRACE_ROOT="$(resolve_download_root "$WORK" atif)"

filter_credential_files "$TRACE_ROOT"

# `tar c .` over an empty directory produces a valid empty archive — what we
# want when /sandbox/atif had no traces. The manifest's empty-note explains it.
tar czf "$TARBALL" -C "$TRACE_ROOT" .

EMPTY_NOTE="ATIF directory was empty. In local mode, finish and cleanly exit a top-level Agent session before retrying. In relay mode, this is expected after successful remote delivery; local files are recovery copies only. See agents/hermes/start.sh for the trace write path."
write_snapshot_manifest "$TARBALL" "$MANIFEST" "$TS" "$SANDBOX_NAME" \
  /sandbox/atif "$EMPTY_NOTE" "${EXCLUDED_FILES[@]:-}"

TARBALL_SIZE=$(stat -c '%s' "$TARBALL")
FILE_COUNT=$(tar tzf "$TARBALL" | wc -l)
echo "Wrote traces: $TARBALL ($FILE_COUNT files, $TARBALL_SIZE bytes)" >&2
echo "Manifest:     $MANIFEST" >&2
# stdout is just the tarball path so callers can `TRACE=$(...)`.
echo "$TARBALL"
