#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Show whether Shrike governance is wired: sandbox presence, the registered
# host-side credential, the installed hook file, and the PreToolUse entry in
# settings.json. Read-only; contacts no external service.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

HOOK_PATH="/sandbox/.openclaw/hooks/shrike-preaction-hook.mjs"
SETTINGS="/sandbox/.openclaw/settings.json"

echo "== Sandbox =="
if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "  present: $NEMOCLAW_SANDBOX_NAME"
else
  echo "  MISSING: $NEMOCLAW_SANDBOX_NAME (run scripts/onboard.sh)"
  exit 0
fi

echo "== Gateway-side Shrike provider =="
run openshell provider get "$SHRIKE_PROVIDER_NAME" 2>/dev/null \
  || echo "  provider not found: $SHRIKE_PROVIDER_NAME (run scripts/onboard.sh)"

echo "== Installed hook =="
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- sh -lc \
  "[ -f '$HOOK_PATH' ] && echo present: $HOOK_PATH || echo MISSING: $HOOK_PATH"

echo "== PreToolUse registration =="
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  node -e '
    const fs=require("fs");
    try {
      const cfg=JSON.parse(fs.readFileSync(process.argv[1],"utf8")||"{}");
      const pre=(cfg.hooks&&cfg.hooks.PreToolUse)||[];
      const shrike=pre.filter(h=>JSON.stringify(h).includes("shrike-preaction-hook"));
      console.log(shrike.length?("registered: "+shrike.length+" entry"):"NOT registered (run scripts/install.sh)");
    } catch { console.log("settings.json unreadable (run scripts/install.sh)"); }
  ' "$SETTINGS"
