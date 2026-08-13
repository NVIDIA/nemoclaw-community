#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -e

# Start Xvfb (X Virtual Framebuffer)
echo "Starting Xvfb on display ${DISPLAY}..."
Xvfb ${DISPLAY} -screen 0 1920x1080x24 &
XVFB_PID=$!

# Wait for X server to be ready
sleep 2

# Start fluxbox window manager
echo "Starting Fluxbox window manager..."
fluxbox &
FLUXBOX_PID=$!

# Start x11vnc server on port 5900
echo "Starting VNC server on port 5900..."
if [ -n "${AXE_A11Y_VNC_PASSWORD:-}" ]; then
  echo "   Using password authentication"
  x11vnc -display ${DISPLAY} -forever -shared -rfbport 5900 \
    -passwd "${AXE_A11Y_VNC_PASSWORD}" &
else
  echo "   Using no-password mode"
  x11vnc -display ${DISPLAY} -forever -shared -rfbport 5900 -nopw &
fi
VNC_PID=$!

echo "✅ VNC server started on port 5900"
echo "   Connect with: vnc://localhost:5900"
echo ""

# Start the MCP server
echo "Starting Axe A11y MCP Server on port ${PORT}..."
exec node server.js
