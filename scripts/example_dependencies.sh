#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Load one example's validated dependencies.toml as allowlisted environment
# variables. The Python parser owns validation and shell escaping.
load_example_dependencies() {
  local example_dir="${1:?example directory is required}"
  local helper_dir exports
  helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exports="$(python3 "$helper_dir/example_dependencies.py" "$example_dir")" || return
  eval "$exports"
}

# Extract the first semantic version printed by a command. Callers may use
# this directly when they need custom pass/fail reporting.
example_dependency_version() {
  "$@" 2>/dev/null \
    | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' \
    | head -n 1 \
    || true
}

require_example_dependency_version() {
  local label="${1:?dependency label is required}"
  local expected="${2:?expected version is required}"
  local installed
  shift 2
  installed="$(example_dependency_version "$@")"
  if [ "${installed#v}" != "${expected#v}" ]; then
    echo "error: $label $expected is required; found ${installed:-unknown}" >&2
    return 1
  fi
}

require_example_harness() {
  local expected="${1:?expected harness is required}"
  local actual="${NEMOCLAW_AGENT:-}"
  if [ -z "$actual" ] && [ -n "${HERMES_VERSION:-}" ]; then
    actual="hermes"
  elif [ -z "$actual" ] && [ -n "${OPENCLAW_VERSION:-}" ]; then
    actual="openclaw"
  fi
  if [ "$actual" != "$expected" ]; then
    echo "error: dependencies.toml must select the $expected harness" >&2
    return 1
  fi
}
