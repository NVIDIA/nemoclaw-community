#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_DIR="$(dirname "${SCRIPT_DIR}")"

cd "${RECIPE_DIR}"

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "📋 Creating .env from .env.example..."
  cp .env.example .env
fi

if [ -f .env ]; then
  # shellcheck disable=SC1091
  source .env
fi
SERVICE_PORT="${AXE_A11Y_SERVICE_PORT:-9010}"
VNC_PORT="${AXE_A11Y_VNC_PORT:-5900}"

echo "🚀 Starting axe-a11y-browser-auditor service via Docker Compose..."
docker compose up -d --build

HEALTH_URL="http://127.0.0.1:${SERVICE_PORT}/healthz"
MAX_RETRIES=30
RETRY_COUNT=0

echo "⏳ Waiting for axe-a11y MCP server health check on ${HEALTH_URL}..."

until curl -fsS "${HEALTH_URL}" > /dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ ${RETRY_COUNT} -ge ${MAX_RETRIES} ]; then
    echo "❌ Service health check failed after ${MAX_RETRIES} attempts."
    docker compose logs --tail=50
    exit 1
  fi
  sleep 1
done

echo "✅ axe-a11y-browser-auditor service is healthy and ready!"
echo "   MCP Endpoint: http://127.0.0.1:${SERVICE_PORT}/mcp"
echo "   VNC Stream:   vnc://localhost:${VNC_PORT}"
