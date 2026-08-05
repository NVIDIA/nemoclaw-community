#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

VERSION="${BLENDER_VERSION:-5.1.2}"
PREFIX="${BLENDER_PREFIX:-/opt}"
SYMLINK="${BLENDER_SYMLINK:-/usr/local/bin/blender}"
WORKDIR="${BLENDER_DOWNLOAD_DIR:-$HOME/Downloads}"
ARCH="$(uname -m)"

usage() {
  cat <<'USAGE'
Install Blender 5.1 for the local architecture.

Environment:
  BLENDER_VERSION                 Default: 5.1.2
  BLENDER_PREFIX                  Default: /opt
  BLENDER_SYMLINK                 Default: /usr/local/bin/blender
  BLENDER_DOWNLOAD_DIR            Default: ~/Downloads
  BLENDER_ALLOW_COMMUNITY_ARM64   Deprecated; no longer required

Notes:
  Official Blender Linux 5.1 binaries are x64. On Linux ARM64 this installs the
  validated lfdevs Blender 5.1.0 native AArch64 build.
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

mkdir -p "$WORKDIR"

case "$ARCH" in
  x86_64|amd64)
    ARCHIVE="blender-${VERSION}-linux-x64.tar.xz"
    URL="https://download.blender.org/release/Blender5.1/${ARCHIVE}"
    SHA_URL="https://download.blender.org/release/Blender5.1/blender-${VERSION}.sha256"
    INSTALL_DIR="${PREFIX}/blender-${VERSION}-linux-x64"
    ;;
  aarch64|arm64)
    VERSION="5.1.0"
    ARCHIVE="blender-5.1.0-git20260325.ae6d847d66fa-aarch64.tar.gz"
    URL="https://github.com/lfdevs/blender-linux-arm64/releases/download/v5.1.0/${ARCHIVE}"
    SHA_URL=""
    INSTALL_DIR="${PREFIX}/blender-5.1.0-linux-aarch64"
    ;;
  *)
    echo "Unsupported architecture: $ARCH" >&2
    exit 2
    ;;
esac

ARCHIVE_PATH="${WORKDIR}/${ARCHIVE}"

if [ ! -f "$ARCHIVE_PATH" ]; then
  curl -fL "$URL" -o "$ARCHIVE_PATH"
fi

if [ -n "$SHA_URL" ]; then
  curl -fsSL "$SHA_URL" -o "${WORKDIR}/blender-${VERSION}.sha256"
  (cd "$WORKDIR" && grep -F " ${ARCHIVE}" "blender-${VERSION}.sha256" | sha256sum -c -)
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

case "$ARCHIVE_PATH" in
  *.tar.xz) tar -xJf "$ARCHIVE_PATH" -C "$TMP_ROOT" ;;
  *.tar.gz) tar -xzf "$ARCHIVE_PATH" -C "$TMP_ROOT" ;;
  *) echo "Unsupported archive: $ARCHIVE_PATH" >&2; exit 2 ;;
esac

EXTRACTED="$(find "$TMP_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$EXTRACTED" ] || [ ! -x "$EXTRACTED/blender" ]; then
  echo "Archive did not contain an executable Blender directory." >&2
  exit 1
fi

sudo rm -rf "$INSTALL_DIR"
sudo mkdir -p "$(dirname "$INSTALL_DIR")"
sudo mv "$EXTRACTED" "$INSTALL_DIR"
sudo ln -sfn "$INSTALL_DIR/blender" "$SYMLINK"

"$SYMLINK" --version | head -n 3
