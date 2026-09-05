#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
# SPDX-License-Identifier: Apache-2.0

# Install the blackwall-guard plugin into an OpenClaw plugin directory.
#
#   scripts/install.sh [DEST_DIR]
#
# DEST_DIR defaults to $OPENCLAW_PLUGIN_DIR, then
# ${OPENCLAW_HOME:-$HOME}/.openclaw/extensions/blackwall-guard — override the
# positional arg or env var if your OpenClaw build loads plugins from elsewhere.
# Copies only what the runtime needs (plugin code, manifest, skills); tests and
# node_modules stay in the repo.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-${OPENCLAW_PLUGIN_DIR:-${OPENCLAW_HOME:-$HOME}/.openclaw/extensions/blackwall-guard}}"

mkdir -p "$DEST/skills"
cp "$SRC/index.ts" "$SRC/openclaw.plugin.json" "$DEST/"
cp -R "$SRC/skills/." "$DEST/skills/"

echo "installed blackwall-guard -> $DEST"
echo
echo "Next steps:"
echo "  1. Enable the plugin (id: nemoclaw-blackwall-guard) in your OpenClaw config."
echo "  2. Deliver the API key. Recommended (NemoClaw): keep the key OUT of the"
echo "     sandbox — import providers/blackwall.yaml as an OpenShell provider and"
echo "     merge policy.yaml's network_policies entry into your sandbox policy, so"
echo "     the L7 proxy injects the real key at egress. Simple alternative:"
echo "     BLACKWALL_API_KEY env var or a key file (see README, 'Enable & configure')."
echo "  3. Run scripts/verify.sh (from inside the sandbox for the injection probe)."
