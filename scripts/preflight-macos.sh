#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir
# SPDX-License-Identifier: Apache-2.0
#
# preflight-macos.sh — read-only environment doctor for NemoClaw on macOS.
#
# Checks for known onboarding failure modes before any install step and
# prints the specific fix for each. Makes NO changes to the system:
# no installs, no writes, no network calls.
#
# Usage: bash scripts/preflight-macos.sh

set -uo pipefail

PASS=0
WARN=0
FAIL=0

green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
red() { printf '\033[31m%s\033[0m\n' "$1"; }

ok()   { green  "  [PASS] $1"; PASS=$((PASS+1)); }
warn() { yellow "  [WARN] $1"; WARN=$((WARN+1)); }
fail() { red    "  [FAIL] $1"; FAIL=$((FAIL+1)); }
fix()  { printf '         fix: %s\n' "$1"; }

echo "NemoClaw macOS preflight"
echo "========================"

echo
echo "system"
if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "this script is for macOS (detected: $(uname -s))"
  exit 1
fi
os_ver="$(sw_vers -productVersion)"
os_major="${os_ver%%.*}"
if (( os_major >= 13 )); then
  ok "macOS ${os_ver}"
else
  fail "macOS ${os_ver} — NemoClaw examples are tested on macOS 13+"
  fix "upgrade macOS via System Settings > General > Software Update"
fi
arch="$(uname -m)"
ok "architecture: ${arch}"

echo
echo "command line tools"
if clt_path="$(xcode-select -p 2>/dev/null)"; then
  ok "developer directory: ${clt_path}"
  clt_ver="$(pkgutil --pkg-info=com.apple.pkg.CLTools_Executables 2>/dev/null | awk '/version:/ {print $2}')"
  if [[ -n "${clt_ver:-}" ]]; then
    ok "CLT version: ${clt_ver}"
  else
    warn "could not read CLT version (Xcode-only setups are fine)"
  fi
else
  fail "Command Line Tools not configured — installers will abort with 'Your Command Line Tools are too outdated'"
  fix "sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install"
fi

echo
echo "homebrew"
if command -v brew >/dev/null 2>&1; then
  ok "brew found: $(command -v brew)"
  brewed_git="$(brew --prefix 2>/dev/null)/bin/git"
  if [[ -x "$brewed_git" ]]; then
    if ! "$brewed_git" --version >/dev/null 2>&1; then
      fail "brewed git is broken (likely 'Symbol not found: _curl_global_trace' vs system libcurl)"
      fix "HOMEBREW_FORCE_BREWED_GIT=0 brew update   # bypasses brewed git"
      fix "then: brew reinstall git   # once update succeeds"
    else
      ok "brewed git runs"
    fi
  fi
  if ! brew config >/dev/null 2>&1; then
    warn "brew config errored — Homebrew metadata may be corrupted"
    fix "brew update-reset && brew update"
  else
    ok "brew config responds"
  fi
else
  warn "Homebrew not found — fine if you install Node/Docker another way"
  fix "install from https://brew.sh if you want brew-managed dependencies"
fi

echo
echo "node.js"
if command -v node >/dev/null 2>&1; then
  node_path="$(command -v node)"
  node_ver="$(node --version | sed 's/^v//')"
  node_major="${node_ver%%.*}"
  if (( node_major >= 22 )); then
    ok "node v${node_ver} at ${node_path}"
  else
    fail "node v${node_ver} — NemoClaw requires Node 22+"
    if [[ -d "$HOME/.nvm" ]]; then
      fix "nvm install 22 && nvm use 22 && nvm alias default 22"
    else
      fix "brew install node@22, or install nvm and: nvm install 22"
    fi
  fi
  npm_prefix="$(npm prefix -g 2>/dev/null || true)"
  if [[ -n "$npm_prefix" ]] && [[ ":$PATH:" != *":${npm_prefix}/bin:"* ]]; then
    warn "npm global bin (${npm_prefix}/bin) is not on PATH — globally installed CLIs will be 'command not found'"
    fix "echo 'export PATH=\"${npm_prefix}/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  else
    ok "npm global bin is on PATH"
  fi
  managers=""
  [[ -d "$HOME/.nvm" ]] && managers+="nvm "
  command -v fnm >/dev/null 2>&1 && managers+="fnm "
  [[ -x "$(brew --prefix 2>/dev/null)/opt/node@22/bin/node" ]] 2>/dev/null && managers+="brew-node@22 "
  if [[ "$(echo "$managers" | wc -w | tr -d ' ')" -gt 1 ]]; then
    warn "multiple Node installs detected (${managers}) — PATH order decides which wins"
    fix "check 'which -a node' and remove or re-order the ones you don't want"
  fi
else
  fail "node not found"
  fix "brew install node@22, or install nvm then: nvm install 22"
fi

echo
echo "docker"
if command -v docker >/dev/null 2>&1; then
  ok "docker CLI found: $(docker --version 2>/dev/null | head -1)"
  if docker info >/dev/null 2>&1; then
    ok "docker daemon is running"
  else
    fail "docker CLI present but daemon not running — sandbox creation will fail"
    fix "open -a Docker   # then wait for the whale icon to settle"
  fi
else
  fail "docker not found — OpenShell sandboxes require a container runtime"
  fix "download Docker Desktop (Apple Silicon) from https://www.docker.com/products/docker-desktop/"
fi

echo
echo "openshell"
if command -v openshell >/dev/null 2>&1; then
  ok "openshell found: $(openshell --version 2>/dev/null | head -1)"
  if openshell gateway info >/dev/null 2>&1; then
    ok "a gateway is registered"
  else
    warn "no gateway registered yet — expected before first onboarding"
    fix "the installer registers one; or: openshell gateway add <endpoint> --local"
  fi
else
  warn "openshell not installed yet — expected before first install"
  fix "see the NemoClaw install docs; the installer will fail fast if CLT (above) is outdated"
fi

echo
echo "========================"
echo "summary: ${PASS} pass, ${WARN} warn, ${FAIL} fail"
if (( FAIL > 0 )); then
  red "resolve [FAIL] items before installing — each has a fix line above"
  exit 1
elif (( WARN > 0 )); then
  yellow "warnings are non-blocking but worth reviewing"
  exit 0
else
  green "environment looks ready"
  exit 0
fi
