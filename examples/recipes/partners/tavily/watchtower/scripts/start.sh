#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Create an OpenClaw-native Cron Job for Watchtower through the supported
# paired OpenClaw CLI. Administrative scope approval is intentionally manual.
# The first attempt can return a requestId; approve that exact request using
# the printed instructions, then rerun this script.
#
# Usage:
#   bash scripts/start.sh [watchlist-path] [every]
#
# Examples:
#   bash scripts/start.sh watchlists/regulatory.yaml 24h
#   bash scripts/start.sh watchlists/regulatory.yaml 5m
#   bash scripts/start.sh watchlists/regulatory.yaml 300   # converted to 5m

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH — run scripts/onboard.sh first" >&2; exit 1; }

WORKSPACE="${WORKSPACE:-/sandbox/.openclaw/workspace}"

WATCHLIST="${1:-${WATCHTOWER_WATCHLIST:-watchlists/regulatory.yaml}}"
EVERY_RAW="${2:-${WATCHTOWER_EVERY:-24h}}"
TIMEOUT_SECONDS="${WATCHTOWER_TIMEOUT_SECONDS:-900}"

slugify() {
  local value="$1"
  value="$(basename "$value")"
  value="${value%.*}"
  printf '%s' "$value" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

format_every() {
  local value="$1"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    if (( value % 3600 == 0 )); then
      printf '%sh' "$((value / 3600))"
    elif (( value % 60 == 0 )); then
      printf '%sm' "$((value / 60))"
    else
      printf '%ss' "$value"
    fi
  else
    printf '%s' "$value"
  fi
}

JOB_NAME="${WATCHTOWER_JOB_NAME:-watchtower-$(slugify "$WATCHLIST")}"
EVERY="$(format_every "$EVERY_RAW")"
MESSAGE="Read /sandbox/.openclaw/skills/watchtower/SKILL.md, then follow its Procedure and Completion gate exactly to run a watchtower sweep of $WATCHLIST from /sandbox/.openclaw/workspace. Complete all six steps, verify the digest, changelog, and state files, and only then reply with a short completion summary—not the digest body."

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

echo "Creating OpenClaw Cron Job in sandbox '$NEMOCLAW_SANDBOX_NAME'"
echo "  job:       $JOB_NAME"
echo "  watchlist: $WATCHLIST"
echo "  every:     $EVERY"
echo "  workspace: $WORKSPACE"

echo "+ openshell sandbox exec --name $NEMOCLAW_SANDBOX_NAME -- openclaw cron add ..."
set +e
OUTPUT="$(openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  openclaw cron add \
    --name "$JOB_NAME" \
    --agent main \
    --every "$EVERY" \
    --session isolated \
    --wake now \
    --message "$MESSAGE" \
    --timeout-seconds "$TIMEOUT_SECONDS" \
    --no-deliver \
    --json 2>&1)"
STATUS=$?
set -e
printf '%s\n' "$OUTPUT"

if (( STATUS != 0 )); then
  REQUEST_ID="$(printf '%s\n' "$OUTPUT" | sed -nE 's/.*requestId["=: ]+([A-Za-z0-9._:-]+).*/\1/p' | head -n 1)"
  echo >&2
  echo "OpenClaw did not create the job. Administrative approval may be required." >&2
  echo "Open the prepared sandbox shell:" >&2
  echo "  nemoclaw $NEMOCLAW_SANDBOX_NAME connect" >&2
  echo >&2
  echo "Then inspect pending requests:" >&2
  echo "  openclaw devices list --json" >&2
  if [[ -n "$REQUEST_ID" ]]; then
    echo "Verify and approve only this exact requestId:" >&2
    echo "  openclaw devices approve $REQUEST_ID" >&2
  else
    echo "Approve only the requestId produced by the cron command, after verifying" >&2
    echo "that it belongs to the expected CLI device and requests operator.admin." >&2
  fi
  echo >&2
  echo "Exit the sandbox shell and rerun this start command." >&2
  exit "$STATUS"
fi

echo
echo "Created. Inspect it in the OpenClaw dashboard under Cron Jobs, or run:"
echo "  bash scripts/status.sh"
