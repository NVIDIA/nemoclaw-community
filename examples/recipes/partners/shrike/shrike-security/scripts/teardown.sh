#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove Shrike governance and its host-side secret. Teardown-safe: leaves no
# service or credential active. By default it removes the PreToolUse hook, the
# uploaded hook file, the host-side credential, and the sandbox.
#
# Keep the sandbox (only un-wire Shrike) with: KEEP_SANDBOX=1 bash scripts/teardown.sh

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

HOOK_PATH="/sandbox/.openclaw/hooks/shrike-preaction-hook.mjs"
SETTINGS="/sandbox/.openclaw/settings.json"

if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Un-wiring Shrike from sandbox '$NEMOCLAW_SANDBOX_NAME'"
  # Drop the Shrike PreToolUse entry, keep any other hooks.
  run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    node -e '
      const fs=require("fs"), p=process.argv[1];
      try {
        const cfg=JSON.parse(fs.readFileSync(p,"utf8")||"{}");
        if (cfg.hooks && Array.isArray(cfg.hooks.PreToolUse)) {
          cfg.hooks.PreToolUse = cfg.hooks.PreToolUse.filter(
            h => !JSON.stringify(h).includes("shrike-preaction-hook"));
          fs.writeFileSync(p, JSON.stringify(cfg,null,2)+"\n");
        }
      } catch {}
    ' "$SETTINGS" || true
  run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- rm -f "$HOOK_PATH" || true

  if [[ -z "${KEEP_SANDBOX:-}" ]]; then
    echo "Removing sandbox '$NEMOCLAW_SANDBOX_NAME'"
    run nemoclaw "$NEMOCLAW_SANDBOX_NAME" destroy -y 2>/dev/null \
      || run openshell sandbox rm "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null || true
  fi
else
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not present — nothing to un-wire."
fi

# Remove the gateway-side Shrike provider + profile unless the sandbox is kept.
if [[ -z "${KEEP_SANDBOX:-}" ]]; then
  echo "Removing Shrike provider '$SHRIKE_PROVIDER_NAME' and profile '$SHRIKE_PROFILE_ID'"
  run openshell provider delete "$SHRIKE_PROVIDER_NAME" 2>/dev/null || true
  run openshell provider profile delete "$SHRIKE_PROFILE_ID" 2>/dev/null || true
fi

echo "Teardown complete."
