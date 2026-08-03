#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../_lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STATE="$WORK/state"
mkdir -p \
  "$STATE/memories" \
  "$STATE/nvteam" \
  "$STATE/sessions" \
  "$STATE/skills/nemoclaw-nvteam/references"

printf 'keep\n' > "$STATE/memories/note.md"
printf 'drop\n' > "$STATE/memories/access-token.txt"
printf 'drop\n' > "$STATE/nvteam/renamed-private-registry.json"
printf 'drop\n' > "$STATE/sessions/persona-authorities.backup.json"
printf 'drop even if overwritten\n' > \
  "$STATE/skills/nemoclaw-nvteam/references/persona-authorities.example.json"
printf 'drop even if overwritten\n' > \
  "$STATE/skills/nemoclaw-nvteam/references/persona-authorities.schema.json"

filter_credential_files "$STATE" >/dev/null 2>&1

[[ -f "$STATE/memories/note.md" ]]
[[ ! -e "$STATE/memories/access-token.txt" ]]
[[ ! -e "$STATE/nvteam/renamed-private-registry.json" ]]
[[ ! -e "$STATE/sessions/persona-authorities.backup.json" ]]
[[ ! -e "$STATE/skills/nemoclaw-nvteam/references/persona-authorities.example.json" ]]
[[ ! -e "$STATE/skills/nemoclaw-nvteam/references/persona-authorities.schema.json" ]]

for expected in \
  memories/access-token.txt \
  nvteam/renamed-private-registry.json \
  sessions/persona-authorities.backup.json \
  skills/nemoclaw-nvteam/references/persona-authorities.example.json \
  skills/nemoclaw-nvteam/references/persona-authorities.schema.json; do
  printf '%s\n' "${EXCLUDED_FILES[@]}" | grep -Fxq "$expected"
done

SAFE_ARCHIVE="$WORK/safe.tar.gz"
tar czf "$SAFE_ARCHIVE" -C "$STATE" .
assert_snapshot_safe_to_restore "$SAFE_ARCHIVE"

UNSAFE_STATE="$WORK/unsafe"
mkdir -p "$UNSAFE_STATE/nvteam"
printf 'private\n' > "$UNSAFE_STATE/nvteam/authorities-renamed.json"
UNSAFE_ARCHIVE="$WORK/unsafe.tar.gz"
tar czf "$UNSAFE_ARCHIVE" -C "$UNSAFE_STATE" .
if assert_snapshot_safe_to_restore "$UNSAFE_ARCHIVE" >/dev/null 2>&1; then
  echo "unsafe authority registry snapshot unexpectedly passed validation" >&2
  exit 1
fi

INVALID_ARCHIVE="$WORK/not-a-snapshot.tar.gz"
printf 'not a tar archive\n' > "$INVALID_ARCHIVE"
if assert_snapshot_safe_to_restore "$INVALID_ARCHIVE" >/dev/null 2>&1; then
  echo "invalid snapshot unexpectedly passed validation" >&2
  exit 1
fi

echo "snapshot safety tests passed"
