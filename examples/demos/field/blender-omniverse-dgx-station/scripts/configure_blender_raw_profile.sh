#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

HOST_IP="${1:?usage: configure_blender_raw_profile.sh <host-ip> [profile-name]}"
PROFILE="${2:-blenderraw}"
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
    --description "Exploratory Blender agent using the raw host Blender MCP."
fi
if [ ! -x "$WRAPPER" ]; then
  hermes profile alias "$PROFILE" --name "$PROFILE"
fi

# A rerun after a sandbox lifecycle operation must refresh skills that were
# reinstalled into the default Hermes home after this profile was first cloned.
mkdir -p "$PROFILE_ROOT/skills"
cp -a /sandbox/.hermes/skills/. "$PROFILE_ROOT/skills/"

python3 /sandbox/configure_hermes_blender_mcp.py "$HOST_IP" --profile "$PROFILE"
hermes profile use "$PROFILE"
hermes mcp test blender

echo "configured raw Blender profile: $PROFILE"
echo "sticky default profile: $PROFILE"
echo "wrapper: $WRAPPER"
