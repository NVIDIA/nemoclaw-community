#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Remove the in-sandbox skill. Does not stop gbr-agent unless
# GBR_TEARDOWN_STOP_AGENT=1. Does not unpair the phone.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"
SANDBOX_NAME="${SANDBOX_NAME:-gbr-pair}"
SKILL_DIR="/sandbox/.openclaw/skills/gbr-remote-operator"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$EXAMPLE_DIR/.env"
  set +a
fi

if command -v openshell >/dev/null 2>&1; then
  if openshell sandbox list 2>/dev/null | grep -qE "^[[:space:]]*${SANDBOX_NAME}[[:space:]]"; then
    openshell sandbox exec --name "$SANDBOX_NAME" -- \
      rm -rf "$SKILL_DIR" /sandbox/bin/gbr-operator-ping || true
    echo "removed skill from sandbox ${SANDBOX_NAME}"
  else
    echo "sandbox ${SANDBOX_NAME} not found; nothing to remove in-sandbox"
  fi
else
  echo "openshell not in PATH; skipped sandbox cleanup"
fi

if [[ "${GBR_TEARDOWN_STOP_AGENT:-0}" == "1" ]]; then
  echo "Stop gbr-agent run on the host (Ctrl+C, or stop the Windows scheduled task)."
fi

echo "Unpair in the phone app Settings before you change hosts. Force-close is not enough."
