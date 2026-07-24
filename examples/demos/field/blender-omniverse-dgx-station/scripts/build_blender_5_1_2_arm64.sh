#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
  cat <<'USAGE'
Build native Blender 5.1.2 for Linux ARM64 DGX-style hosts.

This targets the DGX ARM64 path:
  - Blender source tag: v5.1.2
  - expected commit: ec6e62d40fa9e9d1bea33ad5d00148c99a4f0832
  - native dependency bundle: lib/linux_arm64
  - compiler: gcc-14/g++-14
  - embedded Python: 3.13

Environment:
  BLENDER_ARM64_WORK_ROOT      Default: ~/work/blender-5.1.2-arm64
  BLENDER_SRC                  Default: $BLENDER_ARM64_WORK_ROOT/blender-src
  BLENDER_DEPS_BUILD           Default: $BLENDER_ARM64_WORK_ROOT/blender-deps-build
  BLENDER_BUILD                Default: $BLENDER_ARM64_WORK_ROOT/blender-build-gcc14
  BLENDER_INSTALL              Default: $BLENDER_ARM64_WORK_ROOT/blender-install
  BLENDER_SYMLINK              Default: /usr/local/bin/blender
  BLENDER_BUILD_PARALLELISM    Default: nproc
  BLENDER_ARM64_PATCH          Default: repo patch under patches/

Usage:
  scripts/build_blender_5_1_2_arm64.sh

Expect a long build and at least 100 GiB of free disk.
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

case "$(uname -m)" in
  aarch64|arm64) ;;
  *)
    echo "This source-build path is only for Linux ARM64/aarch64 hosts." >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

VERSION_TAG="v5.1.2"
EXPECTED_COMMIT="ec6e62d40fa9e9d1bea33ad5d00148c99a4f0832"
WORK_ROOT="${BLENDER_ARM64_WORK_ROOT:-$HOME/work/blender-5.1.2-arm64}"
TOOLING_VENV="${TOOLING_VENV:-$WORK_ROOT/tooling-venv}"
BLENDER_SRC="${BLENDER_SRC:-$WORK_ROOT/blender-src}"
BLENDER_DEPS_BUILD="${BLENDER_DEPS_BUILD:-$WORK_ROOT/blender-deps-build}"
BLENDER_BUILD="${BLENDER_BUILD:-$WORK_ROOT/blender-build-gcc14}"
BLENDER_INSTALL="${BLENDER_INSTALL:-$WORK_ROOT/blender-install}"
BLENDER_SYMLINK="${BLENDER_SYMLINK:-/usr/local/bin/blender}"
PATCH_FILE="${BLENDER_ARM64_PATCH:-$REPO_ROOT/patches/blender-5.1.2-arm64-dgx.patch}"
PARALLELISM="${BLENDER_BUILD_PARALLELISM:-$(nproc)}"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need git
need cmake
need python3
need gcc-14
need g++-14

if [ ! -f "$PATCH_FILE" ]; then
  echo "Missing ARM64 patch: $PATCH_FILE" >&2
  exit 1
fi

mkdir -p "$WORK_ROOT"

python3 -m venv "$TOOLING_VENV"
"$TOOLING_VENV/bin/pip" install --upgrade pip
"$TOOLING_VENV/bin/pip" install "conan==2.30.0" ninja

if [ ! -d "$BLENDER_SRC/.git" ]; then
  git clone --branch "$VERSION_TAG" --depth 1 \
    https://projects.blender.org/blender/blender.git "$BLENDER_SRC"
else
  if ! git -C "$BLENDER_SRC" diff --quiet || ! git -C "$BLENDER_SRC" diff --cached --quiet; then
    if ! git -C "$BLENDER_SRC" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
      echo "Existing Blender source has local changes that are not the expected ARM64 patch: $BLENDER_SRC" >&2
      exit 1
    fi
  else
    git -C "$BLENDER_SRC" fetch --depth 1 origin "refs/tags/$VERSION_TAG:refs/tags/$VERSION_TAG" ||
      git -C "$BLENDER_SRC" fetch --tags origin
    git -C "$BLENDER_SRC" checkout "$VERSION_TAG"
  fi
fi

actual_commit="$(git -C "$BLENDER_SRC" rev-parse HEAD)"
if [ "$actual_commit" != "$EXPECTED_COMMIT" ]; then
  echo "Unexpected Blender commit: $actual_commit" >&2
  echo "Expected $EXPECTED_COMMIT for $VERSION_TAG." >&2
  exit 1
fi

if git -C "$BLENDER_SRC" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
  echo "ARM64 Blender patch is already applied."
else
  git -C "$BLENDER_SRC" apply --check "$PATCH_FILE"
  git -C "$BLENDER_SRC" apply "$PATCH_FILE"
fi
git -C "$BLENDER_SRC" diff --check

cmake -S "$BLENDER_SRC/build_files/build_environment" \
  -B "$BLENDER_DEPS_BUILD" \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_MAKE_PROGRAM="$TOOLING_VENV/bin/ninja" \
  -DPACKAGE_USE_UPSTREAM_SOURCES=ON \
  -DDOWNLOAD_DIR="$BLENDER_DEPS_BUILD/downloads" \
  -DPACKAGE_DIR="$BLENDER_DEPS_BUILD/packages" \
  -DHARVEST_TARGET="$BLENDER_SRC/lib/linux_arm64"

cmake --build "$BLENDER_DEPS_BUILD" --parallel "$PARALLELISM"

CC="$(command -v gcc-14)"
CXX="$(command -v g++-14)"

cmake -S "$BLENDER_SRC" \
  -B "$BLENDER_BUILD" \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$BLENDER_INSTALL" \
  -DCMAKE_C_COMPILER="$CC" \
  -DCMAKE_CXX_COMPILER="$CXX" \
  -DCMAKE_MAKE_PROGRAM="$TOOLING_VENV/bin/ninja" \
  -DCMAKE_EXE_LINKER_FLAGS=-Wl,--no-as-needed \
  -DLIBDIR="$BLENDER_SRC/lib/linux_arm64" \
  -DWITH_CYCLES=ON \
  -DWITH_CYCLES_DEVICE_CUDA=ON \
  -DWITH_CYCLES_DEVICE_OPTIX=OFF \
  -DWITH_OPENGL_BACKEND=ON \
  -DWITH_VULKAN_BACKEND=ON \
  -DWITH_PYTHON_INSTALL=ON \
  -DPYTHON_VERSION=3.13

cmake --build "$BLENDER_BUILD" --parallel "$PARALLELISM"
cmake --install "$BLENDER_BUILD"

if [ -n "$BLENDER_SYMLINK" ]; then
  sudo ln -sfn "$BLENDER_INSTALL/blender" "$BLENDER_SYMLINK"
fi

"$BLENDER_INSTALL/blender" --version | head -n 3
"$REPO_ROOT/scripts/verify_dgx_blender.sh" "$BLENDER_INSTALL/blender"

printf 'Installed Blender: %s\n' "$BLENDER_INSTALL/blender"
if [ -n "$BLENDER_SYMLINK" ]; then
  printf 'Symlinked Blender: %s\n' "$BLENDER_SYMLINK"
fi
