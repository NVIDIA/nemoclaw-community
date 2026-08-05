#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 2 (after onboard.sh): install the watchtower assets into the
# sandbox using `openshell sandbox upload` — the documented mechanism for
# pushing files into a sandbox from the host.
#
#   skills/watchtower/  -> /sandbox/.openclaw/skills/watchtower/  (skill discovery dir)
#   watchlists/         -> $WORKSPACE/watchlists/
#   prompts/AGENTS.md   -> $WORKSPACE/AGENTS.md
#   state/, outputs/     created under $WORKSPACE
#
# WORKSPACE defaults to the single-agent workspace path; override for named
# agents (e.g. WORKSPACE=/sandbox/.openclaw/workspace-main).
#
# Idempotent: re-running re-uploads the same files in place.
#
# Try after this script:
#   $ bash scripts/sweep.sh   # one immediate sweep
#   $ bash scripts/start.sh   # OpenClaw Cron Job scheduler

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH — run scripts/onboard.sh first" >&2; exit 1; }

WORKSPACE="${WORKSPACE:-/sandbox/.openclaw/workspace}"
SKILLS_DIR="/sandbox/.openclaw/skills"

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

echo "Installing watchtower assets into sandbox '$NEMOCLAW_SANDBOX_NAME' (workspace: $WORKSPACE)"

run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  mkdir -p "$SKILLS_DIR" "$WORKSPACE/state" "$WORKSPACE/outputs"

# `openshell sandbox upload` copies the source directory INTO the
# destination (cp semantics), so upload to the parent directory.
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$EXAMPLE_DIR/skills/watchtower" "$SKILLS_DIR/"
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$EXAMPLE_DIR/watchlists" "$WORKSPACE/"
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$EXAMPLE_DIR/prompts/AGENTS.md" "$WORKSPACE/"
echo
echo "Installed. Run once with: bash scripts/sweep.sh"
echo "Start the OpenClaw Cron Job with: bash scripts/start.sh"
