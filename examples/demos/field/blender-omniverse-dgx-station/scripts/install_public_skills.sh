#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX_NAME:-ov-blender-hermes}}"
OV_REPO="${2:-${OV_REPO:-$HOME/work/ov-blender-hermes-demo/omniverse-labs/projects/ov-blender-example}}"
OV_SKILLS_REF="${OV_SKILLS_REF:-main}"
GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'USAGE'
Install public ov-blender-example skills into a running NemoHermes sandbox.

Usage:
  install_public_skills.sh [sandbox-name] [ov-blender-example-checkout]

Environment:
  OV_SKILLS_REF=<ref>            Git ref to read skills from (default: main;
                                 use current to skip the fetch)
  NEMOCLAW_SANDBOX_NAME         Default sandbox name
  OV_REPO                       Default ov-blender-example checkout
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if ! command -v nemohermes >/dev/null 2>&1; then
  echo "nemohermes is not on PATH. Source your shell profile or add ~/.local/bin to PATH." >&2
  exit 1
fi

if [ ! -f "$OV_REPO/skills/manifest.json" ] || [ ! -f "$OV_REPO/AGENTS.md" ]; then
  echo "official ov-blender-example project not found: $OV_REPO" >&2
  exit 1
fi

repo_root="$(git -C "$OV_REPO" rev-parse --show-toplevel 2>/dev/null || true)"
project_prefix="$(git -C "$OV_REPO" rev-parse --show-prefix 2>/dev/null || true)"
if [ -z "$repo_root" ] || [ -z "$project_prefix" ]; then
  echo "ov-blender-example must be inside an omniverse-labs Git checkout: $OV_REPO" >&2
  exit 1
fi

if [ "$OV_SKILLS_REF" != "current" ]; then
  git -C "$repo_root" fetch origin "$OV_SKILLS_REF"
  git -C "$repo_root" checkout FETCH_HEAD -- \
    "${project_prefix}skills" "${project_prefix}AGENTS.md"
elif [ ! -f "$OV_REPO/skills/manifest.json" ]; then
  echo "skills/manifest.json not found and OV_SKILLS_REF=current was set." >&2
  exit 1
fi

count=0
for skill_dir in "$OV_REPO"/skills/*; do
  if [ -f "$skill_dir/SKILL.md" ]; then
    nemohermes "$SANDBOX" skill install "$skill_dir"
    count=$((count + 1))
  fi
done

guide_count=0
for skill_dir in "$GUIDE_ROOT"/skills/*; do
  if [ -f "$skill_dir/SKILL.md" ]; then
    nemohermes "$SANDBOX" skill install "$skill_dir"
    guide_count=$((guide_count + 1))
  fi
done

# Hermes 0.18 flattens nested skill files during `skill install`. Restore the
# path documented by blender-python-api-verification explicitly.
api_skill_root="/sandbox/.hermes/skills/blender-python-api-verification"
nemohermes "$SANDBOX" exec --timeout 30 -- \
  mkdir -p "$api_skill_root/scripts"
nemohermes sandbox upload "$SANDBOX" \
  "$GUIDE_ROOT/skills/blender-python-api-verification/scripts/search_blender_api.py" \
  "$api_skill_root/scripts/"
nemohermes "$SANDBOX" exec --timeout 30 -- \
  test -f "$api_skill_root/scripts/search_blender_api.py"

echo "installed $count official OV skills and $guide_count guide-specific skills into sandbox $SANDBOX"
