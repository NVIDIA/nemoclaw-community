#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$EXAMPLE_DIR/.env"
  set +a
fi

SANDBOX_NAME="${SANDBOX_NAME:-deep-research-worker}"

echo "== 1/2 stop host-side worker =="
(cd "$EXAMPLE_DIR" && docker compose down)

if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell not found; skipping sandbox cleanup."
  exit 0
fi

if ! openshell sandbox list 2>/dev/null | grep -qE "^[[:space:]]*${SANDBOX_NAME}[[:space:]]"; then
  echo "Sandbox '${SANDBOX_NAME}' not found; skipping sandbox cleanup."
  exit 0
fi

echo "== 2/2 remove installed skill assets =="
openshell sandbox exec --name "$SANDBOX_NAME" -- rm -rf \
  /sandbox/.openclaw/skills/deep-research \
  /sandbox/bin/deep-research || true

echo "Teardown complete."
