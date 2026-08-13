#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_DIR="$(dirname "${SCRIPT_DIR}")"

cd "${RECIPE_DIR}"

echo "🛑 Stopping axe-a11y-browser-auditor service..."
docker compose down -v

echo "✅ Teardown complete."
