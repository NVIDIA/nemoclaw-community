#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Download GitHub Release v0.6.0 gbr-agent and check a hard-coded digest.
# Do not use a website install.sh. Do not trust a co-downloaded SHA256SUMS
# file as the only check.

set -euo pipefail

VER="${GBR_AGENT_VERSION:-v0.6.0}"
BASE="https://github.com/LinespottingOrg/GrokBuildRemote-Agents/releases/download/${VER}"
DEST_DIR="${GBR_AGENT_DEST_DIR:-$HOME/.local/bin}"
DEST="${DEST_DIR}/gbr-agent"

os="$(uname -s)"
arch="$(uname -m)"
case "$os-$arch" in
  Darwin-arm64) ASSET="gbr-agent-darwin-arm64"; SHA="7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8" ;;
  Darwin-x86_64) ASSET="gbr-agent-darwin-amd64"; SHA="62673a6856342a87d4a2a659bc1de92200aa19a5b60d88d252254940820f0b7f" ;;
  Linux-x86_64) ASSET="gbr-agent-linux-amd64"; SHA="fb54724367882497f2e8e05e40ecdeb4be29e008e6c865fc5c426cf464e6ad6e" ;;
  Linux-aarch64) ASSET="gbr-agent-linux-arm64"; SHA="9e9d7ca45bb0c4ded9d04226136013e9b64ae30f16bcf03069d35e9c38171cb9" ;;
  *)
    echo "unsupported host $os/$arch. On Windows use scripts/install-gbr-agent.ps1." >&2
    exit 1
    ;;
esac

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
curl -fsSL -o "$tmpdir/$ASSET" "$BASE/$ASSET"

if command -v shasum >/dev/null 2>&1; then
  printf '%s  %s\n' "$SHA" "$tmpdir/$ASSET" | shasum -a 256 -c -
elif command -v sha256sum >/dev/null 2>&1; then
  printf '%s  %s\n' "$SHA" "$tmpdir/$ASSET" | sha256sum -c -
else
  echo "need shasum or sha256sum" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
install -m 0755 "$tmpdir/$ASSET" "$DEST"
"$DEST" version
echo "installed $DEST"
