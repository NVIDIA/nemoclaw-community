#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Copy the remote-operator skill into an existing OpenShell sandbox.

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

command -v openshell >/dev/null 2>&1 || {
  echo "openshell not in PATH" >&2
  exit 1
}

openshell sandbox exec --name "$SANDBOX_NAME" -- mkdir -p "$SKILL_DIR/scripts" /sandbox/bin
openshell sandbox cp "$EXAMPLE_DIR/skills/gbr-remote-operator/SKILL.md" \
  "${SANDBOX_NAME}:${SKILL_DIR}/SKILL.md"
openshell sandbox cp "$EXAMPLE_DIR/skills/gbr-remote-operator/scripts/operator-ping.sh" \
  "${SANDBOX_NAME}:${SKILL_DIR}/scripts/operator-ping.sh"
openshell sandbox cp "$EXAMPLE_DIR/skills/gbr-remote-operator/scripts/operator-ping.sh" \
  "${SANDBOX_NAME}:/sandbox/bin/gbr-operator-ping"
openshell sandbox exec --name "$SANDBOX_NAME" -- \
  chmod +x "$SKILL_DIR/scripts/operator-ping.sh" /sandbox/bin/gbr-operator-ping

echo "installed skill gbr-remote-operator into sandbox ${SANDBOX_NAME}"
