#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# One-shot watchtower sweep: sends the sweep prompt to the OpenClaw agent in
# a single non-interactive turn. Useful for ad-hoc runs and for debugging the
# same prompt that the OpenClaw Cron Job runs on schedule.
#
# Usage:
#   bash scripts/sweep.sh [watchlist-path]
#
# The watchlist path is relative to the agent workspace inside the sandbox
# (default: watchlists/regulatory.yaml). Override the sandbox with
# NEMOCLAW_SANDBOX_NAME (default: watchtower).

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH — run scripts/onboard.sh first" >&2; exit 1; }

WATCHLIST="${1:-${WATCHTOWER_WATCHLIST:-watchlists/regulatory.yaml}}"
MESSAGE="Read /sandbox/.openclaw/skills/watchtower/SKILL.md, then follow its Procedure and Completion gate exactly to run a watchtower sweep of $WATCHLIST from /sandbox/.openclaw/workspace. Complete all six steps, verify the digest, changelog, and state files, and only then reply with a short completion summary—not the digest body."

echo "Sweeping $WATCHLIST in sandbox '$NEMOCLAW_SANDBOX_NAME'"
# No --local: NemoClaw sandboxes reject it (it would bypass the gateway's
# managed inference route, secret scanning, and network policy).
run openshell sandbox exec --tty --name "$NEMOCLAW_SANDBOX_NAME" -- \
  openclaw agent --agent main -m "$MESSAGE"
