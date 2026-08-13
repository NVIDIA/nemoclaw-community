#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

HEALTH_URL="http://127.0.0.1:9010/healthz"
MCP_URL="http://127.0.0.1:9010/mcp"

echo "🔍 Verifying axe-a11y MCP server health check..."
if curl -fsS "${HEALTH_URL}" > /dev/null 2>&1; then
  echo "✅ Health check passed: ${HEALTH_URL}"
else
  echo "❌ Health check failed at ${HEALTH_URL}. Is the container running?"
  echo "   Run ./scripts/bring-up.sh first."
  exit 1
fi

echo "🔍 Sending test JSON-RPC request to MCP endpoint..."
RESPONSE=$(curl -s -X POST "${MCP_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }' || true)

if echo "${RESPONSE}" | grep -q "audit_page"; then
  echo "✅ MCP endpoint verified! Available tools detected."
  exit 0
else
  echo "⚠️ Warning: MCP response did not contain expected tool list."
  echo "Response: ${RESPONSE}"
  exit 1
fi
