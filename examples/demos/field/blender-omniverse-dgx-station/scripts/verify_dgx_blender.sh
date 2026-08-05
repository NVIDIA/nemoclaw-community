#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -u

blender_input="${1:-$(command -v blender 2>/dev/null || true)}"
blender="$blender_input"
if [ -n "$blender_input" ] && command -v readlink >/dev/null 2>&1; then
  blender_resolved="$(readlink -f "$blender_input" 2>/dev/null || true)"
  if [ -n "$blender_resolved" ]; then
    blender="$blender_resolved"
  fi
fi
failures=0
warnings=0

ok() { printf 'OK: %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; warnings=$((warnings + 1)); }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

arch="$(uname -m)"
case "$arch" in
  aarch64|arm64) ok "host architecture is $arch" ;;
  *) fail "host architecture is $arch, expected aarch64/arm64" ;;
esac

if [ -z "$blender" ] || [ ! -x "$blender" ]; then
  fail "Blender is not executable: ${blender_input:-not found}"
  printf 'RESULT: %d failure(s), %d warning(s)\n' "$failures" "$warnings"
  exit 1
fi

if [ "$blender" != "$blender_input" ]; then
  ok "resolved Blender symlink: $blender_input -> $blender"
fi

file_info="$(file "$blender" 2>&1)"
case "$file_info" in
  *"ARM aarch64"*|*"ARM64"*) ok "Blender executable is native ARM64" ;;
  *) fail "Blender executable is not ARM64: $file_info" ;;
esac

version_info="$("$blender" --version 2>&1)"
version_line="$(printf '%s\n' "$version_info" | sed -n '1p')"
case "$version_line" in
  "Blender 5.1.0") ok "$version_line" ;;
  "Blender 5.1"*) warn "validated DGX Station reference uses Blender 5.1.0; found $version_line" ;;
  *) fail "expected Blender 5.1.x; found ${version_line:-no version output}" ;;
esac

python_info="$("$blender" --background --factory-startup --python-expr 'import platform,sys; print("MACHINE=" + platform.machine()); print("EMBEDDED_PYTHON=" + ".".join(map(str, sys.version_info[:3])))' 2>&1)"
python_line="$(printf '%s\n' "$python_info" | sed -n 's/^EMBEDDED_PYTHON=//p' | tail -1)"
machine_line="$(printf '%s\n' "$python_info" | sed -n 's/^MACHINE=//p' | tail -1)"
case "$python_line" in
  3.13.*) ok "embedded Python is $python_line" ;;
  *) fail "expected embedded Python 3.13.x; found ${python_line:-unknown}" ;;
esac
case "$machine_line" in
  aarch64|arm64) ok "embedded Python machine is $machine_line" ;;
  *) fail "embedded Python machine is ${machine_line:-unknown}" ;;
esac

if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_info="$(nvidia-smi --query-gpu=index,name,driver_version --format=csv,noheader 2>&1)"
  if [ -n "$gpu_info" ]; then
    ok "NVIDIA GPUs are visible"
    printf '%s\n' "$gpu_info" | sed 's/^/  /'
  else
    fail "nvidia-smi returned no GPUs"
  fi
else
  warn "nvidia-smi is not on PATH"
fi

if [ -d "$HOME/.config/blender/5.1/extensions/.user/user_default/ovrtx_blender_example" ] ||
   [ -d "$HOME/.config/blender/5.1/extensions/user_default/ovrtx_blender_example" ]; then
  ok "OVRTX Blender extension is installed"
else
  warn "OVRTX Blender extension was not found in the Blender 5.1 user extensions"
fi

if (( failures > 0 )); then
  printf 'RESULT: %d failure(s), %d warning(s)\n' "$failures" "$warnings"
  exit 1
fi

printf 'RESULT: ready (%d warning(s))\n' "$warnings"
printf 'Launch pin, if GPU 0 is the RTX PRO device: CUDA_VISIBLE_DEVICES=0 OVRTX_ACTIVE_CUDA_GPUS=0 %q\n' "$blender"
