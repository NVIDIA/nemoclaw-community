#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Capture the agent's accumulated state ("collective wisdom") to a host-side
# tarball that survives sandbox deletion.
#
# What gets captured: everything under /sandbox/.hermes-data/ — Hermes's
# writable state directory. Concretely:
#   memories/   sessions/   skills/   plugins/   cron/   plans/
#   workspace/  profiles/   cache/    pairing/
# These are the dirs Hermes writes to during a conversation. SOUL.md is also
# under .hermes-data but is image-baked at build time, not runtime-mutated.
#
# Credential hygiene: file-name-pattern matches (.env, *secret*, *token*,
# auth-profiles.json, etc.) are excluded from the tarball before storage so
# snapshots are safely shareable. Mirrors the spirit (not the exact format)
# of NemoClaw's createSnapshotBundle() in nemoclaw/src/commands/migration-state.ts:679.
#
# Output: $EXAMPLE_DIR/.snapshots/{ISO-timestamp}.tar.gz plus a sidecar
# manifest.json. Snapshot path is printed on stdout so callers can capture it:
#   $ SNAP=$(bash scripts/snapshot.sh)
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

mkdir -p "$SNAPSHOT_DIR"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
TARBALL="$SNAPSHOT_DIR/$TS.tar.gz"
MANIFEST="$SNAPSHOT_DIR/$TS.manifest.json"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading /sandbox/.hermes-data from $SANDBOX_NAME …" >&2
openshell sandbox download "$SANDBOX_NAME" /sandbox/.hermes-data "$WORK/" >/dev/null

# `download` may produce either $WORK/.hermes-data/... or $WORK/... depending on
# the OpenShell version's basename handling. Handle both shapes.
if [[ -d "$WORK/.hermes-data" ]]; then
  STATE_ROOT="$WORK/.hermes-data"
else
  STATE_ROOT="$WORK"
fi

# ── Credential filter ───────────────────────────────────────────────────
# File-level exclusion of obvious credential-bearing files. Conservative —
# just matches names. For a richer content-aware sanitize, mirror the regex
# pass in NemoClaw's migration-state.ts. The patterns below are deliberately
# coarse: better to drop a non-secret file than ship a real token.
EXCLUDED=()
while IFS= read -r -d '' f; do
  EXCLUDED+=("${f#"$STATE_ROOT/"}")
  rm -f "$f"
done < <(find "$STATE_ROOT" -type f \( \
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
# Tar from inside STATE_ROOT so entries are relative paths from the
# .hermes-data root (no leading directory). Restore can then untar straight
# into /sandbox/.hermes-data without --strip-components fiddling.
tar czf "$TARBALL" -C "$STATE_ROOT" .

# ── Manifest ────────────────────────────────────────────────────────────
FILE_COUNT=$(tar tzf "$TARBALL" | wc -l)
TARBALL_SIZE=$(stat -c '%s' "$TARBALL")
python3 - "$TARBALL" "$MANIFEST" "$TS" "$FILE_COUNT" "$TARBALL_SIZE" \
    "$SANDBOX_NAME" "${EXCLUDED[@]:-}" <<'PY'
import json, os, sys
tarball, manifest_path, ts, file_count, size, sandbox = sys.argv[1:7]
excluded = [x for x in sys.argv[7:] if x]
manifest = {
    "version": 1,
    "captured_at": ts,
    "sandbox_name": sandbox,
    "source_path": "/sandbox/.hermes-data",
    "tarball": os.path.basename(tarball),
    "tarball_bytes": int(size),
    "file_count": int(file_count),
    "excluded_files": excluded,
    "note": "File-level credential filter applied. Inspect with `tar tzf <path>`.",
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
PY

echo "Wrote snapshot: $TARBALL ($FILE_COUNT files, $TARBALL_SIZE bytes)" >&2
echo "Manifest:       $MANIFEST" >&2
# stdout is just the tarball path, so callers can do `SNAP=$(...)`.
echo "$TARBALL"
