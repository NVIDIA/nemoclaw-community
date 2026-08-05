#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX_NAME:-ov-blender-hermes}}"
VERSION="${BLENDER_API_VERSION:-5.1}"
VERSION_TOKEN="${VERSION//./_}"
GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/nemoclaw-blender"
ARCHIVE="$CACHE_ROOT/blender_python_reference_${VERSION_TOKEN}.zip"
SANDBOX_ARCHIVE="/sandbox/reference/blender_python_reference_${VERSION_TOKEN}.zip"
SANDBOX_DEST="/sandbox/reference/blender-python-api-${VERSION}"
SANDBOX_INDEX="$SANDBOX_DEST/api-search.sqlite3"
URL="https://docs.blender.org/api/${VERSION}/blender_python_reference_${VERSION_TOKEN}.zip"

command -v nemohermes >/dev/null 2>&1 || {
  echo "nemohermes is not on PATH. Use a login shell or add ~/.local/bin to PATH." >&2
  exit 1
}

if [ "${BLENDER_API_FORCE:-0}" != "1" ] && \
  nemohermes "$SANDBOX" exec --timeout 30 -- \
    test -f "$SANDBOX_INDEX" >/dev/null 2>&1; then
  echo "Blender $VERSION Python API reference is already installed in $SANDBOX_DEST"
  exit 0
fi

nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/build_blender_api_index.py" \
  /sandbox/

if [ "${BLENDER_API_FORCE:-0}" != "1" ] && \
  nemohermes "$SANDBOX" exec --timeout 30 -- \
    test -f "$SANDBOX_DEST/index.html" >/dev/null 2>&1; then
  nemohermes "$SANDBOX" exec --timeout 180 -- \
    python /sandbox/build_blender_api_index.py "$SANDBOX_DEST"
  echo "indexed the existing Blender $VERSION Python API reference"
  exit 0
fi

mkdir -p "$CACHE_ROOT"
if [ ! -s "$ARCHIVE" ]; then
  echo "downloading the official Blender $VERSION Python API reference (about 92 MB)"
  curl -fL --retry 3 "$URL" -o "$ARCHIVE.part"
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

python3 -m zipfile -t "$ARCHIVE" >/dev/null
nemohermes sandbox upload "$SANDBOX" "$ARCHIVE" /sandbox/reference/
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/scripts/install_blender_api_reference.py" \
  /sandbox/
nemohermes "$SANDBOX" exec --timeout 180 -- \
  python /sandbox/install_blender_api_reference.py "$SANDBOX_ARCHIVE" "$SANDBOX_DEST"
nemohermes "$SANDBOX" exec --timeout 180 -- \
  python /sandbox/build_blender_api_index.py "$SANDBOX_DEST"

echo "installed official Blender $VERSION Python API docs in $SANDBOX_DEST"
