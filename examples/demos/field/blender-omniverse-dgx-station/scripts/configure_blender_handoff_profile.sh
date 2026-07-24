#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

HOST_IP="${1:?usage: configure_blender_handoff_profile.sh <host-ip> [profile-name]}"
PROFILE="${2:-blenderhandoff}"
PROFILE_ROOT="/sandbox/.hermes/profiles/$PROFILE"
WRAPPER="/sandbox/.local/bin/$PROFILE"

if [[ ! "$HOST_IP" =~ ^[A-Za-z0-9._:-]+$ ]]; then
  echo "host IP contains unsupported characters: $HOST_IP" >&2
  exit 2
fi
if [[ ! "$PROFILE" =~ ^[a-z0-9]+$ ]]; then
  echo "profile name must contain only lowercase letters and digits" >&2
  exit 2
fi

if [ ! -d "$PROFILE_ROOT" ]; then
  hermes profile create "$PROFILE" --clone \
    --description "Bounded Blender and OpenUSD handoff agent using typed host MCP operations."
fi
if [ ! -x "$WRAPPER" ]; then
  hermes profile alias "$PROFILE" --name "$PROFILE"
fi

# Refresh skills on reruns after the default Hermes skill set was reinstalled.
# The mutable skills toolset remains disabled below; the boundary skill is
# preloaded read-only by the wrapper.
mkdir -p "$PROFILE_ROOT/skills"
cp -a /sandbox/.hermes/skills/. "$PROFILE_ROOT/skills/"

python3 /sandbox/configure_hermes_blender_mcp.py "$HOST_IP" \
  --profile "$PROFILE" --include-workflow

"$WRAPPER" tools disable \
  web browser terminal file code_execution vision image_gen tts skills todo memory \
  session_search clarify delegation cronjob computer_use

"$WRAPPER" mcp test blender-workflow

# The built-in skills toolset includes skill_manage, which lets the model write
# files inside installed skills. Keep that mutable toolset disabled and preload
# the read-only boundary guidance on every chat invocation instead.
cat >"$WRAPPER" <<EOF
#!/bin/sh
if [ "\${1:-}" = "chat" ]; then
  shift
  exec /usr/local/bin/hermes -p "$PROFILE" chat \
    -s blender-host-sandbox-boundary "\$@"
fi
exec /usr/local/bin/hermes -p "$PROFILE" "\$@"
EOF
chmod 0755 "$WRAPPER"

echo "configured isolated Hermes profile: $PROFILE"
echo "wrapper: $WRAPPER"
