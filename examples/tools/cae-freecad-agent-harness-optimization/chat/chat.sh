#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# chat.sh [MESH.obj|MESH.stl]: chat with the CAD agent in the browser, the agent in a container.
# Settings: see README.md.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
AGENT=$(cd "${CAD_AGENT_DIR:-$HERE/results/final-agent}" && pwd)
WORK=${CAD_WORK:-$HERE/cad-work}; mkdir -p "$WORK"; WORK=$(cd "$WORK" && pwd)
PORT=${CAD_WEB_PORT:-8765}
MESH=(); ARG=
if [ $# -ge 1 ]; then  # mounted read-only; web.py turns it into reference.obj
  EXT=$(basename "$1" | tr A-Z a-z); EXT=${EXT##*.}
  case $EXT in obj|stl) ;; *) echo "chat.sh: $1 is not a mesh; give an .obj or .stl file" >&2; exit 2 ;; esac
  MESH=(-v "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")":/mesh.$EXT:ro); ARG=/mesh.$EXT
fi
echo "CAD agent chat: http://localhost:$PORT  (work folder $WORK; Ctrl-C stops it)"
# --init: an init process reaps what a stopped task leaves behind.
exec docker run --rm --init --memory 3g --add-host=host.docker.internal:host-gateway \
  -v "$AGENT":/agent:ro -v "$WORK":/app -v "$HERE/chat":/chat:ro -v "$HERE/harness":/harness:ro ${MESH[@]+"${MESH[@]}"} -w /app \
  -e CAD_HELIX_URL="${CAD_HELIX_URL:-http://host.docker.internal:8080}" -e NHX_WORKSPACE \
  -e CAD_MODEL -e CAD_AGENT_TIMEOUT="${CAD_CHAT_TIMEOUT:-900}" -e CHAT_BASE_URL -e CHAT_API_KEY \
  -p "127.0.0.1:$PORT:8765" -e CAD_WEB_PORT="$PORT" --name "cad-web-$PORT" cad-env python /chat/web.py /agent $ARG
