#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Bring up the TAO computer-vision recipe: install the TAO skill bank, ensure a
# CPU-only NemoClaw sandbox, and wire the host `tao` MCP server into it. Also the
# resume command — rerunning reuses a healthy sandbox and restarts the server.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
cd "$ROOT"

[ -f .env ] && { set -a; . ./.env; set +a; }

SANDBOX="${TAO_SANDBOX:-tao}"
WORKSPACE="${TAO_WORKSPACE:-$HOME/tao-workspace}"
SKILL_REF="${TAO_SKILL_REF:-main}"
BANK_REPO="https://github.com/NVIDIA-TAO/tao-skills-bank"
BANK_DIR="$ROOT/external/tao-skills-bank"
INTEG="$BANK_DIR/integrations/nemoclaw"

for bin in docker uv nemoclaw git; do
  command -v "$bin" >/dev/null || { echo "error: '$bin' not on PATH" >&2; exit 1; }
done
[ -n "${NEMOCLAW_PROVIDER_KEY:-}" ] || { echo "error: set NEMOCLAW_PROVIDER_KEY in .env" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "error: Docker is not available" >&2; exit 1; }

echo "==> Installing the TAO skill bank ($SKILL_REF)"
if [ -d "$BANK_DIR/.git" ]; then
  git -C "$BANK_DIR" fetch -q origin "$SKILL_REF" && git -C "$BANK_DIR" checkout -q -B "$SKILL_REF" FETCH_HEAD
else
  git clone --depth 1 -b "$SKILL_REF" "$BANK_REPO" "$BANK_DIR"
fi
[ -f "$INTEG/setup-tao-nemoclaw.sh" ] || {
  echo "error: this tao-skills-bank ref has no integrations/nemoclaw/ integration." >&2
  echo "       Use a ref that ships the NemoClaw integration (TAO 7.1+)." >&2
  exit 1
}

echo "==> Ensuring a CPU-only NemoClaw sandbox '$SANDBOX'"
if ! nemoclaw list 2>/dev/null | grep -qw "$SANDBOX"; then
  if [ -x "$INTEG/create-nemoclaw-sandbox.sh" ]; then
    NEMOCLAW_PROVIDER_KEY="$NEMOCLAW_PROVIDER_KEY" "$INTEG/create-nemoclaw-sandbox.sh" openclaw "$SANDBOX"
  else
    echo "error: sandbox '$SANDBOX' not found. Onboard one first:  nemoclaw onboard" >&2
    exit 1
  fi
fi

echo "==> Wiring the host tao MCP server + skills into '$SANDBOX'"
mkdir -p "$WORKSPACE"
( cd "$INTEG" && SKILL_LOCAL="$BANK_DIR" ./setup-tao-nemoclaw.sh "$SANDBOX" "$WORKSPACE" )

cat <<EOF

==> Ready. Put a dataset under $WORKSPACE/<name>/ and ask the agent:

    nemoclaw $SANDBOX agent --agent main -m "What TAO models can you train, and what data do you need?"

Verify:   bash scripts/verify.sh
Teardown: bash scripts/tear-down.sh [--destroy-sandbox]
EOF
