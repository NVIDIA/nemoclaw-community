#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_DIR="$(dirname "${SCRIPT_DIR}")"

cd "${RECIPE_DIR}"

echo "🛑 Stopping axe-a11y-browser-auditor service..."
docker compose down -v

if [ "${1:-}" == "--purge" ]; then
  echo "🧹 Purging persistent state and artifacts..."
  rm -rf state/profile state/artifacts
  echo "✅ Purge complete."
else
  echo "ℹ️  Note: Persistent profile and artifacts in state/ were not removed."
  echo "   Run './scripts/teardown.sh --purge' to delete them."
fi

echo "✅ Teardown complete."
