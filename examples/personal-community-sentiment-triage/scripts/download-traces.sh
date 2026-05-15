#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Pull Agent Trajectory Format (ATIF) traces off the running sandbox into a
# host-side tarball for offline analysis.
#
# Where ATIF comes from: Hermes's NeMo-Flow integration writes per-turn
# trajectory records to HERMES_NEMO_FLOW_ATIF_DIR=/tmp/atif inside the
# sandbox (see agents/hermes/start.sh). The directory is ephemeral — it
# lives on the sandbox's writable layer and disappears with the container
# on tear-down — so capture before destroying the sandbox if you want to
# keep traces from that session.
#
# The agent writes ATIF records to /tmp/atif on every
# turn. If the directory is still empty when this script runs, the most
# likely cause is that the agent hasn't had a turn yet — interact with it
# (e.g. send a DM or email) and try again. The tarball is still produced
# in the empty case, with a corresponding note in the manifest.
#
# Output: $EXAMPLE_DIR/.traces/atif-{ISO-timestamp}.tar.gz plus a sidecar
# manifest.json. Tarball path is printed on stdout so callers can capture:
#   $ TRACE=$(bash scripts/download-traces.sh)
#
# OpenShell commands you'll see:
#   - openshell sandbox download <name> <sandbox-path> <local-dest>

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

# Validate the sandbox is up before trying to download from it.
if ! openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" | grep -qi ready; then
  echo "Sandbox $SANDBOX_NAME is not ready — bring it up first" >&2
  exit 1
fi

TRACES_DIR="${TRACES_DIR:-$EXAMPLE_DIR/.traces}"
mkdir -p "$TRACES_DIR"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
TARBALL="$TRACES_DIR/atif-$TS.tar.gz"
MANIFEST="$TRACES_DIR/atif-$TS.manifest.json"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading /tmp/atif from $SANDBOX_NAME …" >&2
openshell sandbox download "$SANDBOX_NAME" /tmp/atif "$WORK/" >/dev/null

# `download` may produce either $WORK/atif/... or $WORK/... depending on the
# OpenShell version's basename handling. Handle both shapes.
if [[ -d "$WORK/atif" ]]; then
  TRACE_ROOT="$WORK/atif"
else
  TRACE_ROOT="$WORK"
fi

# ── Credential filter ───────────────────────────────────────────────────
# Same conservative pattern-match filter snapshot.sh uses. ATIF traces are
# unlikely to contain raw credentials (the agent sees placeholders via the
# L7 proxy, not real tokens), but file-name filtering is cheap and matches
# the rest of this example's defence-in-depth posture.
EXCLUDED=()
while IFS= read -r -d '' f; do
  EXCLUDED+=("${f#"$TRACE_ROOT/"}")
  rm -f "$f"
done < <(find "$TRACE_ROOT" -type f \( \
    -iname '.env' -o -iname '*.env' -o \
    -iname '*secret*' -o -iname '*token*' -o \
    -iname 'auth-profiles*' -o -iname 'credentials*' -o \
    -iname 'id_rsa*' -o -iname '*.pem' -o -iname '*.key' \
  \) -print0)

if [[ "${#EXCLUDED[@]}" -gt 0 ]]; then
  echo "Excluded ${#EXCLUDED[@]} credential-shaped file(s):" >&2
  printf '  %s\n' "${EXCLUDED[@]}" >&2
fi

# ── Tar it up ───────────────────────────────────────────────────────────
# Tar from inside TRACE_ROOT so entries are relative paths from the ATIF
# root. `tar c .` over an empty directory produces a valid (32-byte
# gzipped) empty archive, which is what we want when /tmp/atif had no
# traces — the manifest carries the explanation.
tar czf "$TARBALL" -C "$TRACE_ROOT" .

# ── Manifest ────────────────────────────────────────────────────────────
FILE_COUNT=$(tar tzf "$TARBALL" | wc -l)
TARBALL_SIZE=$(stat -c '%s' "$TARBALL")
python3 - "$TARBALL" "$MANIFEST" "$TS" "$FILE_COUNT" "$TARBALL_SIZE" \
    "$SANDBOX_NAME" "${EXCLUDED[@]:-}" <<'PY'
import json, os, sys
tarball, manifest_path, ts, file_count, size, sandbox = sys.argv[1:7]
excluded = [x for x in sys.argv[7:] if x]
file_count = int(file_count)
if file_count == 0:
    note = (
        "ATIF directory was empty. The agent has likely not had a turn yet "
        "since bring-up — interact with it (DM, email, etc.) and re-run. "
        "See agents/hermes/start.sh for the trace write path."
    )
else:
    note = "File-level credential filter applied. Inspect with `tar tzf <path>`."
manifest = {
    "version": 1,
    "captured_at": ts,
    "sandbox_name": sandbox,
    "source_path": "/tmp/atif",
    "tarball": os.path.basename(tarball),
    "tarball_bytes": int(size),
    "file_count": file_count,
    "excluded_files": excluded,
    "note": note,
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
PY

echo "Wrote traces: $TARBALL ($FILE_COUNT files, $TARBALL_SIZE bytes)" >&2
echo "Manifest:     $MANIFEST" >&2
# stdout is just the tarball path, so callers can do `TRACE=$(...)`.
echo "$TARBALL"
