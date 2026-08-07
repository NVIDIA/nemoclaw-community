#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove Shrike governance and its host-side secret. Teardown-safe: leaves no
# service or credential active. By default it disables + uninstalls the plugin,
# detaches the provider, removes the host-side credential + profile, and removes
# the sandbox.
#
# Keep the sandbox (only un-wire Shrike) with: KEEP_SANDBOX=1 bash scripts/teardown.sh
#
# Note: in INSTALL_MODE=image the plugin is baked into the sandbox image, so a
# `plugins uninstall` only affects the running container — a `rebuild` would
# restore it. For image installs, removing the sandbox (default) is the clean
# teardown.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }
command -v nemoclaw  >/dev/null || { echo "nemoclaw not in PATH"  >&2; exit 1; }

if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Un-wiring Shrike from sandbox '$NEMOCLAW_SANDBOX_NAME'"

  # Disable + uninstall the plugin (best-effort; the sandbox may be mid-teardown).
  run sb_openclaw plugins disable "$SHRIKE_PLUGIN_ID" 2>/dev/null || true
  run sb_openclaw plugins uninstall "$SHRIKE_PLUGIN_ID" 2>/dev/null || true
  run sb_exec rm -rf "$PLUGIN_STAGE_DIR" 2>/dev/null || true

  # Detach the provider from the sandbox.
  run openshell sandbox provider detach "$NEMOCLAW_SANDBOX_NAME" "$SHRIKE_PROVIDER_NAME" 2>/dev/null || true

  # Reload the gateway so the plugin stops firing (only if the sandbox survives).
  if [[ -n "${KEEP_SANDBOX:-}" ]]; then
    restart_gateway 2>/dev/null || true
  fi

  if [[ -z "${KEEP_SANDBOX:-}" ]]; then
    echo "Removing sandbox '$NEMOCLAW_SANDBOX_NAME'"
    run nemoclaw "$NEMOCLAW_SANDBOX_NAME" destroy -y 2>/dev/null \
      || run openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null || true
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
