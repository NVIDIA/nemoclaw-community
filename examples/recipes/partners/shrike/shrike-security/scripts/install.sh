#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 2 (after onboard.sh): install the Shrike PreToolUse hook into the
# sandbox so every matched tool call is governed by Shrike before it runs.
#
#   hooks/shrike-preaction-hook.mjs -> /sandbox/.openclaw/hooks/shrike-preaction-hook.mjs
#   .openclaw/settings.json          registers a PreToolUse hook that invokes it
#
# The hook classifies each action (sql / command / file_write / web_search /
# general), calls Shrike's enforce plane, and maps the verdict to an OpenClaw
# permission decision (allow/warn -> allow; block/require_approval -> deny).
# Auth rides the `openshell:resolve:env:SHRIKE_API_KEY` placeholder — the raw
# key stays on the host (see onboard.sh).
#
# Idempotent: re-running re-uploads the hook and re-writes the settings entry.
#
# Try after this script:
#   $ bash scripts/verify.sh   # allowed/denied live validation

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH — run scripts/onboard.sh first" >&2; exit 1; }

HOOKS_DIR="/sandbox/.openclaw/hooks"
SETTINGS="/sandbox/.openclaw/settings.json"
HOOK_PATH="$HOOKS_DIR/shrike-preaction-hook.mjs"

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

echo "Installing Shrike PreToolUse hook into sandbox '$NEMOCLAW_SANDBOX_NAME'"

run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- mkdir -p "$HOOKS_DIR"

# `openshell sandbox upload` copies the source INTO the destination dir.
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" \
  "$EXAMPLE_DIR/hooks/shrike-preaction-hook.mjs" "$HOOKS_DIR/"
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- chmod +x "$HOOK_PATH"

# Register the PreToolUse hook in settings.json without clobbering existing
# settings. node is present in the sandbox (OpenClaw runtime); merge in place.
echo "+ registering PreToolUse hook in $SETTINGS"
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  node -e '
    const fs = require("fs");
    const path = process.argv[1];
    const hook = process.argv[2];
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(path, "utf8") || "{}"); } catch {}
    cfg.hooks = cfg.hooks || {};
    const entry = {
      matcher: "*",
      hooks: [{ type: "command", command: "node " + hook }],
    };
    // Replace any prior Shrike entry; keep other PreToolUse hooks intact.
    const prior = Array.isArray(cfg.hooks.PreToolUse) ? cfg.hooks.PreToolUse : [];
    const others = prior.filter(
      (h) => !JSON.stringify(h).includes("shrike-preaction-hook")
    );
    cfg.hooks.PreToolUse = [...others, entry];
    fs.mkdirSync(require("path").dirname(path), { recursive: true });
    fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
    console.log("PreToolUse hook registered:", hook);
  ' "$SETTINGS" "$HOOK_PATH"

echo
echo "Installed. Validate allowed/denied behavior with: bash scripts/verify.sh"
