#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Show whether Shrike governance is wired: sandbox presence, the gateway-side
# credential, the attachment of that provider to the sandbox, and the runtime
# state of the before_tool_call plugin. Read-only; contacts no external service.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }
command -v nemoclaw  >/dev/null || { echo "nemoclaw not in PATH"  >&2; exit 1; }

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

echo "== Provider attached to sandbox =="
if provider_attached; then
  echo "  attached: $SHRIKE_PROVIDER_NAME -> $NEMOCLAW_SANDBOX_NAME"
else
  echo "  NOT attached (run scripts/onboard.sh) — enforce calls cannot authenticate"
fi

echo "== Governance plugin (runtime) =="
if plugin_loaded; then
  # Print the fields that matter: status, whether the before_tool_call hook is
  # registered, and the plugin shape. Falls back to a plain note if the JSON
  # shape changes across OpenClaw versions.
  plugin_inspect_json \
    | node -e '
        let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
          try {
            const j=JSON.parse(s);
            const p=j.plugin||{};
            const hooks=j.typedHooks||[];
            console.log("  loaded:   "+(p.status||"?")+" (enabled="+(p.enabled??"?")+", activated="+(p.activated??"?")+")");
            console.log("  shape:    "+(j.shape||"?"));
            console.log("  hooks:    "+(p.hookCount??hooks.length)+" "+JSON.stringify(hooks.map(h=>h.name)));
          } catch { console.log("  loaded (inspect JSON unparsed)"); }
        });' \
    || echo "  loaded (inspect unavailable)"
else
  echo "  NOT loaded (run scripts/install.sh, or INSTALL_MODE=image bash scripts/onboard.sh)"
fi
