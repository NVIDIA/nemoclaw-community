#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

OV_REPO="${1:-${OV_REPO:-$HOME/work/ov-blender-hermes-demo/omniverse-labs/projects/ov-blender-example}}"
GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_SKILLS_DIR="${CODEX_SKILLS_DIR:-$HOME/.agents/skills}"

usage() {
  cat <<'USAGE'
Install the project Codex coaching skills and link the upstream OV add-on skills.

Usage:
  install_codex_skills.sh [ov-blender-example-checkout]

Environment:
  OV_REPO             Default OV repository checkout
  CODEX_SKILLS_DIR    Codex user skill directory (default: ~/.agents/skills)
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -f "$OV_REPO/skills/manifest.json" ]; then
  echo "official OV project with skills not found: $OV_REPO" >&2
  exit 1
fi

mkdir -p "$CODEX_SKILLS_DIR"

link_skill() {
  local source_dir="$1"
  local skill_name target
  skill_name="$(basename "$source_dir")"
  target="$CODEX_SKILLS_DIR/$skill_name"

  if [ ! -f "$source_dir/SKILL.md" ]; then
    return
  fi

  if [ -L "$target" ] && [ "$(readlink -f "$target")" = "$(readlink -f "$source_dir")" ]; then
    echo "already linked: $skill_name"
    return
  fi

  if [ -e "$target" ] || [ -L "$target" ]; then
    echo "refusing to replace existing Codex skill: $target" >&2
    exit 1
  fi

  ln -s "$(readlink -f "$source_dir")" "$target"
  echo "linked: $skill_name"
}

project_count=0
for skill_dir in "$GUIDE_ROOT"/codex-skills/*; do
  if [ -f "$skill_dir/SKILL.md" ]; then
    link_skill "$skill_dir"
    project_count=$((project_count + 1))
  fi
done

count=0
for skill_dir in "$OV_REPO"/skills/*; do
  if [ -f "$skill_dir/SKILL.md" ]; then
    link_skill "$skill_dir"
    count=$((count + 1))
  fi
done

echo "Linked $project_count project coaching skills and $count upstream OV skills from $OV_REPO"
