#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 2 (after onboard.sh): install the Shrike governance plugin into the
# sandbox so every tool call is evaluated by Shrike's enforce plane before it
# runs.
#
# Governance is an OpenClaw `before_tool_call` plugin (plugin/), the supported
# runtime interception path — the same contract NemoClaw's own secret-scanner
# uses. It is NOT a Claude-style PreToolUse settings.json hook (the OpenClaw
# runtime does not load those). The plugin classifies each action (sql /
# command / file_write / web_search / general), calls Shrike's enforce plane,
# and maps the verdict to an OpenClaw decision (allow/warn -> allow;
# block/require_approval -> block). Auth rides the
# `openshell:resolve:env:SHRIKE_API_KEY` placeholder — the raw key stays on the
# gateway (see onboard.sh).
#
# INSTALL_MODE=image (default): the plugin is already baked into the sandbox
#   image at onboard time (scripts/build-image.sh) — this script only verifies
#   it loaded. This is the supported, durable path.
# INSTALL_MODE=runtime (dev-only): build the plugin on the host, stage it into
#   the sandbox OUTSIDE the managed extensions dir, then `openclaw plugins
#   install` + `enable` and restart the gateway. Not durable across `rebuild`
#   and can contend with the config-integrity guard; use for local iteration.
#
# Idempotent: re-running re-stages + re-installs (runtime) or re-verifies (image).
#
# Try after this script:
#   $ bash scripts/verify.sh   # allowed/denied live validation

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH — run scripts/onboard.sh first" >&2; exit 1; }
command -v nemoclaw  >/dev/null || { echo "nemoclaw not in PATH — run scripts/onboard.sh first"  >&2; exit 1; }

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

# The provider must be attached for the plugin's enforce call to authenticate.
# onboard.sh attaches it; ensure it here too so install is self-sufficient.
attach_provider

if [[ "$INSTALL_MODE" == "image" ]]; then
  echo "INSTALL_MODE=image — the plugin is baked into the sandbox image; verifying it loaded."
  if plugin_loaded; then
    echo "Plugin '$SHRIKE_PLUGIN_ID' is loaded."
    echo
    echo "Installed. Validate allowed/denied behavior with: bash scripts/verify.sh"
    exit 0
  fi
  echo "error: plugin '$SHRIKE_PLUGIN_ID' is not loaded in the image." >&2
  echo "Re-run onboarding in image mode: INSTALL_MODE=image bash scripts/onboard.sh" >&2
  exit 1
fi

# ---- runtime install (DEV / quick-try) --------------------------------------
# This path installs into the live sandbox and, on first enable, must re-bless
# the managed config integrity hash to restart the gateway (see
# restart_gateway_guarded). That re-bless is unsigned/operator-asserted and the
# install is NOT durable across `nemoclaw <sb> rebuild`. For production, prefer
# INSTALL_MODE=image (baked + provenance-guarded). See the README.

echo "Installing Shrike governance plugin into sandbox '$NEMOCLAW_SANDBOX_NAME' (runtime / dev)"

# 1) Build the plugin's dist/ on the host.
build_plugin

# 2) Stage the plugin into the sandbox, OUTSIDE the managed extensions dir.
#    Only the runtime artifacts are staged: the manifest, package.json, and the
#    compiled dist/. The plugin imports nothing from `openclaw` (structural
#    types), so it carries no node_modules — nothing else is needed.
echo "+ staging plugin into $PLUGIN_STAGE_DIR"
run sb_exec rm -rf "$PLUGIN_STAGE_DIR"
run sb_exec mkdir -p "$PLUGIN_STAGE_DIR"
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$PLUGIN_DIR/package.json"          "$PLUGIN_STAGE_DIR/"
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$PLUGIN_DIR/openclaw.plugin.json"  "$PLUGIN_STAGE_DIR/"
run openshell sandbox upload "$NEMOCLAW_SANDBOX_NAME" "$PLUGIN_DIR/dist"                   "$PLUGIN_STAGE_DIR/"

# 3) Install + enable the plugin, then restart the gateway so it loads.
#    --force makes re-runs idempotent (plain install refuses if already present).
run sb_openclaw plugins install --force "$PLUGIN_STAGE_DIR"
run sb_openclaw plugins enable "$SHRIKE_PLUGIN_ID"
restart_gateway_guarded

# 4) Confirm it loaded (status=loaded, before_tool_call hook registered).
if plugin_loaded; then
  echo "Plugin '$SHRIKE_PLUGIN_ID' is loaded."
else
  echo "error: plugin '$SHRIKE_PLUGIN_ID' did not report loaded after install." >&2
  echo "Diagnose with: nemoclaw $NEMOCLAW_SANDBOX_NAME exec -- env HOME=/sandbox openclaw plugins doctor" >&2
  exit 1
fi

echo
echo "Installed. Validate allowed/denied behavior with: bash scripts/verify.sh"
