#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Read-only macOS doctor for NemoClaw Community onboarding.
# Usage: bash scripts/preflight-macos.sh
# Does not install packages, mutate PATH, or write credentials.

set -euo pipefail

FAIL=0
WARN=0

pass() { printf '  [OK]  %s\n' "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN + 1)); }
fail() { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL + 1)); }
fix() { printf '         fix: %s\n' "$1"; }

echo "NemoClaw Community macOS preflight (read-only)"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script is for macOS. Detected $(uname -s)."
  echo
  echo "Result: FAIL (${FAIL} failed)"
  exit 1
fi

ARCH="$(uname -m)"
echo "== Host"
pass "macOS $(sw_vers -productVersion) (${ARCH})"
if [[ "${ARCH}" != "arm64" ]]; then
  warn "Apple Silicon (arm64) is the tested macOS path. Intel may need extra workarounds."
fi

echo
echo "== Command Line Tools"
if xcode-select -p >/dev/null 2>&1; then
  CLT_PATH="$(xcode-select -p)"
  pass "Command Line Tools at ${CLT_PATH}"
else
  fail "Command Line Tools are missing."
  fix "sudo xcode-select --install"
fi

if pkgutil --pkg-info=com.apple.pkg.CLTools_Executables >/dev/null 2>&1; then
  CLT_VER="$(pkgutil --pkg-info=com.apple.pkg.CLTools_Executables | awk '/version:/ {print $2}')"
  pass "CLT package version ${CLT_VER}"
else
  warn "CLT package metadata missing. OpenShell installers may report 'Command Line Tools are too outdated'."
  fix "sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install"
fi

echo
echo "== Homebrew"
if command -v brew >/dev/null 2>&1; then
  pass "brew $(brew --version | head -n 1)"
  if brew config >/dev/null 2>&1; then
    pass "brew config runs"
  else
    fail "brew config failed. Common cause: Homebrew git vs system libcurl ('Symbol not found: _curl_global_trace')."
    fix "brew update-reset"
    fix "If git is still broken: brew reinstall git"
  fi
else
  fail "Homebrew is not on PATH."
  fix "https://docs.brew.sh/Installation"
fi

echo
echo "== Node >= 22"
NODE_BIN=""
if command -v node >/dev/null 2>&1; then
  NODE_BIN="$(command -v node)"
fi
if [[ -z "${NODE_BIN}" ]]; then
  fail "node is not on PATH."
  fix "brew install node@22 && brew link --overwrite --force node@22"
  fix "If you use nvm/fnm, open a new shell so PATH includes the version manager."
else
  NODE_VER="$("${NODE_BIN}" -v 2>/dev/null || true)"
  NODE_MAJOR="$(printf '%s\n' "${NODE_VER#v}" | cut -d. -f1)"
  if [[ -n "${NODE_MAJOR}" && "${NODE_MAJOR}" -ge 22 ]]; then
    pass "node ${NODE_VER} at ${NODE_BIN}"
  else
    fail "node ${NODE_VER:-unknown} is below 22."
    fix "brew install node@22, or nvm install 22, then confirm 'command -v node' in this shell"
  fi
fi

echo
echo "== Docker"
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    pass "Docker daemon reachable"
  else
    fail "docker is installed but the daemon is not reachable."
    fix "Start Docker Desktop (or Colima) and wait until 'docker info' succeeds"
  fi
else
  fail "docker is not on PATH."
  fix "Install Docker Desktop for Mac or Colima, then re-run this script"
fi

echo
echo "== OpenShell"
if command -v openshell >/dev/null 2>&1; then
  pass "openshell on PATH ($(command -v openshell))"
else
  warn "openshell is not on PATH yet. Install it after this doctor is green."
  fix "Follow the example README OpenShell install after Command Line Tools and Node pass"
fi

echo
if [[ "${FAIL}" -gt 0 ]]; then
  echo "Result: FAIL (${FAIL} failed, ${WARN} warnings)"
  echo "Re-run: bash scripts/preflight-macos.sh"
  exit 1
fi
echo "Result: PASS (${WARN} warnings)"
exit 0
