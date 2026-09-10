#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
# SPDX-License-Identifier: Apache-2.0

# Remove an installed blackwall-guard plugin.
#
#   scripts/uninstall.sh [DEST_DIR]
#
# Same DEST_DIR resolution as install.sh. Refuses to delete a directory that
# does not look like this plugin (manifest id check), so a mistyped path can't
# take out something else.
set -euo pipefail

DEST="${1:-${OPENCLAW_PLUGIN_DIR:-${OPENCLAW_HOME:-$HOME}/.openclaw/extensions/blackwall-guard}}"

if [ ! -d "$DEST" ]; then
  echo "nothing to remove: $DEST does not exist"
  exit 0
fi
if ! grep -q '"id": *"nemoclaw-blackwall-guard"' "$DEST/openclaw.plugin.json" 2>/dev/null; then
  echo "refusing to delete $DEST: no blackwall-guard manifest found there" >&2
  exit 1
fi

rm -rf "$DEST"
echo "removed $DEST"
echo "Also remove the plugin entry (id: nemoclaw-blackwall-guard) from your OpenClaw"
echo "config, and — if you imported them — the OpenShell provider (nemoclaw-blackwall)"
echo "and the 'blackwall' network_policies entry from your sandbox policy."
