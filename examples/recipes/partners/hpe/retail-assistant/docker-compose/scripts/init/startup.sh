#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NOTE: no "set -e" — the NemoClaw installer emits transient errors
# (connection refused) during the gateway boot race. We handle errors
# explicitly where needed.

# ═══════════════════════════════════════════════════════════════
# NemoClaw Docker-Compose startup script
# Runs inside the workspace (ubuntu:24.04) container.
# Uses host Docker socket directly (no DinD).
# ═══════════════════════════════════════════════════════════════

# ─── Helper: resolve the workspace container IP ───────────────
# The sandbox can't reach 127.0.0.1 or host.openshell.internal —
# it must use the real Docker network IP of this container.
get_workspace_ip() {
  hostname -I | awk '{print $1}'
}

# ─── Helper: resolve the retail_api container IP ──────────────
get_retail_api_ip() {
  # With network_mode: host, compose DNS is unavailable;
  # retail_api publishes 8002->8000 on the host.
  echo "127.0.0.1"
}

# ─── Helper: parse OPENAI_BASE_URL into scheme/host/port/path ──
# Users provide a full OpenAI-compatible base URL, e.g.
#   http://localhost:8600/v1            (local tunnel / vLLM / Dynamo)
#   http://nemotron-super:8000/v1       (vLLM container on same network)
#   https://integrate.api.nvidia.com/v1 (hosted endpoint)
# The socat proxy still needs a raw host:port and the gateway
# provider needs the path (e.g. /v1), so we split it into:
#   OPENAI_SCHEME, OPENAI_HOST, OPENAI_PORT, OPENAI_PATH
parse_openai_base_url() {
  # Backward-compat: derive from legacy DYNAMO_HOST (host:port) if set.
  if [ -z "${OPENAI_BASE_URL:-}" ] && [ -n "${DYNAMO_HOST:-}" ]; then
    OPENAI_BASE_URL="http://${DYNAMO_HOST}/v1"
    echo "[Config] OPENAI_BASE_URL not set; derived from legacy DYNAMO_HOST: $OPENAI_BASE_URL"
  fi
  if [ -z "${OPENAI_BASE_URL:-}" ]; then
    echo "[Config] ERROR: OPENAI_BASE_URL is not set."
    return 1
  fi
  local url="$OPENAI_BASE_URL"
  OPENAI_SCHEME="http"
  case "$url" in
    https://*) OPENAI_SCHEME="https"; url="${url#https://}" ;;
    http://*)  OPENAI_SCHEME="http";  url="${url#http://}" ;;
  esac
  local hostport="${url%%/*}"
  if [ "$hostport" = "$url" ]; then
    OPENAI_PATH=""
  else
    OPENAI_PATH="/${url#*/}"
  fi
  OPENAI_PATH="${OPENAI_PATH%/}"            # drop any trailing slash
  OPENAI_HOST="${hostport%%:*}"
  if [ "${hostport#*:}" = "$hostport" ]; then
    [ "$OPENAI_SCHEME" = "https" ] && OPENAI_PORT=443 || OPENAI_PORT=80
  else
    OPENAI_PORT="${hostport##*:}"
  fi
  echo "[Config] OPENAI_BASE_URL=$OPENAI_BASE_URL -> host=$OPENAI_HOST port=$OPENAI_PORT path='${OPENAI_PATH}' scheme=$OPENAI_SCHEME"
}

# ─── Helper: socat target for the inference proxy ─────────────
# Plain TCP for http upstreams; originate TLS for https upstreams
# so the sandbox can keep talking plain http to the local socat port.
openai_socat_target() {
  if [ "$OPENAI_SCHEME" = "https" ]; then
    echo "OPENSSL:${OPENAI_HOST}:${OPENAI_PORT},verify=0"
  else
    echo "TCP:${OPENAI_HOST}:${OPENAI_PORT}"
  fi
}

# ─── Helper: ensure the inference host resolves via /etc/hosts ─
# nip.io DNS can be unreliable and container names need resolving
# when running with network_mode: host. Add an /etc/hosts entry so
# socat (and curl) can always resolve OPENAI_HOST.
ensure_openai_dns() {
  local host="$OPENAI_HOST"
  # Already resolvable? Nothing to do.
  if getent hosts "$host" >/dev/null 2>&1; then
    return
  fi
  # nip.io: extract embedded IP
  if echo "$host" | grep -q "nip.io"; then
    local ip
    ip=$(echo "$host" | grep -oP '\d+\.\d+\.\d+\.\d+')
    if [ -n "$ip" ]; then
      echo "[DNS] Adding /etc/hosts (nip.io): $ip $host"
      echo "$ip $host" >> /etc/hosts
      return
    fi
  fi
  # Docker container name: resolve via docker inspect (needed with network_mode: host)
  local container_ip
  container_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$host" 2>/dev/null | awk '{print $1}')
  if [ -n "$container_ip" ]; then
    echo "[DNS] Adding /etc/hosts (docker): $container_ip $host"
    echo "$container_ip $host" >> /etc/hosts
    return
  fi
  echo "[DNS] WARNING: Cannot resolve OPENAI_HOST='$host'"
}

# ─── Helper: find the sandbox Docker container ───────────────
# With Docker-driver OpenShell, the sandbox is a regular Docker container.
get_sandbox_container() {
  local name="${1:-$SANDBOX_NAME}"
  local cid
  cid=$(docker ps --filter "name=${name}" --format '{{.Names}}' 2>/dev/null | head -1)
  if [ -z "$cid" ]; then
    cid=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i "$name" | head -1)
  fi
  echo "$cid"
}

# [1/4] Install packages
echo "[1/4] Installing packages..."
apt-get update -qq
apt-get install -y -qq docker.io socat curl ca-certificates gnupg binutils git >/dev/null 2>&1

# Install Node.js 22 (required by NemoClaw and post-install scripts)
if ! command -v node >/dev/null 2>&1; then
  echo "[1/4] Installing Node.js 22..."
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
  apt-get install -y -qq nodejs >/dev/null 2>&1
fi
echo "[1/4] Node.js $(node --version) installed"

# ─── Inference endpoint: parse OPENAI_BASE_URL + ensure DNS ──
# Must happen BEFORE socat starts, otherwise socat fails to connect.
parse_openai_base_url
ensure_openai_dns
# The sandbox/installer talk to the local socat proxy; preserve the
# upstream path (e.g. /v1) from OPENAI_BASE_URL.
# INFER_PORT is the workspace port the inference socat listens on. Make it
# configurable so the example can coexist with a busy host port 8000
# (workspace runs network_mode: host, so this port is shared with the host).
INFER_PORT="${SOCAT_INFERENCE_PORT:-8000}"
export NEMOCLAW_ENDPOINT_URL="http://host.openshell.internal:${INFER_PORT}${OPENAI_PATH}"

# [2/4] Start socat proxies
echo "[2/4] Starting socat proxies..."
# Inference port: OpenAI-compatible LLM endpoint (forwarded to OPENAI_BASE_URL)
socat TCP-LISTEN:${INFER_PORT},fork,reuseaddr "$(openai_socat_target)" &
SOCAT_8000_PID=$!
# Port 8001: Retail API — forwarded into the sandbox as workspace_ip:8001
# With network_mode: host, use localhost:8002 (retail_api publishes 8002→8000)
socat TCP-LISTEN:8001,fork,reuseaddr TCP:localhost:8002 &
echo "127.0.0.1 host.openshell.internal" >> /etc/hosts
sleep 1

# Verify the inference socat is alive (may have died if DNS still failed
# or the port is already in use on the host).
sleep 2
if ! kill -0 "$SOCAT_8000_PID" 2>/dev/null; then
  echo "[socat-${INFER_PORT}] WARNING: socat died, restarting..."
  socat TCP-LISTEN:${INFER_PORT},fork,reuseaddr "$(openai_socat_target)" &
  SOCAT_8000_PID=$!
  sleep 1
  if ! kill -0 "$SOCAT_8000_PID" 2>/dev/null; then
    echo "[socat-${INFER_PORT}] ERROR: socat failed again. Inference will not work."
    echo "[socat-${INFER_PORT}] Is host port ${INFER_PORT} already in use? Set SOCAT_INFERENCE_PORT to a free port in .env."
  fi
fi

# [3/4] Verify Docker daemon (host Docker socket)
echo "[3/4] Verifying Docker daemon..."
if docker info >/dev/null 2>&1; then
  echo "Docker ready (host socket)"
else
  echo "Docker not available via host socket"; exit 1
fi

# Clear stale Docker build cache so the NemoClaw sandbox image builds
# fresh (avoids version mismatch between cached OpenClaw layers and
# the installer's patches).
echo "[3/4] Pruning Docker build cache..."
docker builder prune -af 2>/dev/null || docker system prune -af 2>/dev/null || true

# Export Telegram build args before installer runs so they are available
# as Docker image build args (NEMOCLAW_MESSAGING_*_B64).
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_USER_ID:-}" ]; then
  echo "[Telegram] Exporting messaging channel env vars..."
  export NEMOCLAW_MESSAGING_CHANNELS_B64
  NEMOCLAW_MESSAGING_CHANNELS_B64=$(echo -n '["telegram"]' | base64 -w 0)
  export NEMOCLAW_MESSAGING_ALLOWED_IDS_B64
  # Build JSON array from comma-separated TELEGRAM_USER_ID (e.g. "123,456" → ["123","456"])
  IDS_JSON=$(echo "$TELEGRAM_USER_ID" | tr ',' '\n' | sed 's/^/"/;s/$/"/' | paste -sd ',' | sed 's/^/[/;s/$/]/')
  NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=$(printf '{"telegram":%s}' "$IDS_JSON" | base64 -w 0)
fi

# [4/4] Run official NemoClaw installer
echo "[4/4] Running NemoClaw installer..."

# Prepare shared volume for gateway/sandbox binaries (Fix #9).
# The gateway bind-mounts openshell-sandbox into sandbox containers and the
# nemoclaw CLI spawns these binaries locally. The compose file mounts the
# shared volume at the SAME path on host and container ($NEMOCLAW_BIN_PATH),
# so a single path works for both the HOST docker daemon (bind-mount sources)
# and processes spawned INSIDE this container.
BIN_PATH="${NEMOCLAW_BIN_PATH:-/tmp/nemoclaw-bin}"
mkdir -p "$BIN_PATH"

# Check if a sandbox already exists (from a previous run). If yes, skip onboard.
if nemoclaw "${NEMOCLAW_SANDBOX_NAME:-retail-demo-assistant}" status >/dev/null 2>&1; then
  echo "[4/4] Sandbox already exists, skipping installer."
  INSTALL_OK=true
else
  # Use NemoClaw v0.0.50 (latest tagged release, commit 14b2be2)
  _INSTALL_CMD="curl -fsSL https://nvidia.com/nemoclaw.sh | NEMOCLAW_INSTALL_REF=14b2be2933ca8e001f66575a1e7bb4f166f401d8 bash -s -- --fresh"

  # ─── First attempt ─────────────────────────────────────────
  # The installer installs CLI + binaries, then runs onboard.
  # Onboard will likely FAIL because the gateway tries to bind-mount
  # openshell-sandbox from the HOST filesystem where it doesn't exist yet.
  echo "[4/4] First installer attempt (installs CLI + binaries)..."
  eval "$_INSTALL_CMD" || true

  # ─── Fix #9: Copy binaries to host-visible shared volume ───
  if [ -f /usr/local/bin/openshell-gateway ] && [ -f /usr/local/bin/openshell-sandbox ]; then
    echo "[Fix9] Copying OpenShell binaries to shared volume ($BIN_PATH)..."
    # Remove first to avoid "Text file busy" if the sandbox is using the
    # binary. Use rm -rf because a previous failed `docker run` may have
    # auto-created these paths as empty DIRECTORIES (rm -f can't remove dirs).
    rm -rf "$BIN_PATH/openshell-gateway" "$BIN_PATH/openshell-sandbox" 2>/dev/null || true
    cp /usr/local/bin/openshell-gateway "$BIN_PATH/openshell-gateway"
    cp /usr/local/bin/openshell-sandbox "$BIN_PATH/openshell-sandbox"
    chmod +x "$BIN_PATH/openshell-gateway" "$BIN_PATH/openshell-sandbox"
    # Verify the copies are real regular files before relying on them.
    if [ ! -f "$BIN_PATH/openshell-gateway" ] || [ ! -f "$BIN_PATH/openshell-sandbox" ]; then
      echo "[Fix9] ERROR: binaries did not copy to $BIN_PATH as regular files."
    fi
    export NEMOCLAW_OPENSHELL_GATEWAY_BIN="$BIN_PATH/openshell-gateway"
    export NEMOCLAW_OPENSHELL_SANDBOX_BIN="$BIN_PATH/openshell-sandbox"
  fi

  # Check if sandbox container is actually running (more reliable than
  # nemoclaw status, which fails if the inference smoke check didn't pass).
  _SANDBOX_CHECK=$(get_sandbox_container "${NEMOCLAW_SANDBOX_NAME:-retail-demo-assistant}")
  if [ -n "$_SANDBOX_CHECK" ]; then
    echo "[4/4] Sandbox container '$_SANDBOX_CHECK' is running after first attempt."
    INSTALL_OK=true
  elif nemoclaw "${NEMOCLAW_SANDBOX_NAME:-retail-demo-assistant}" status >/dev/null 2>&1; then
    echo "[4/4] Sandbox exists after first attempt."
    INSTALL_OK=true
  else
    echo "[4/4] Sandbox not created. Applying Fix #9 and retrying..."

    # Kill any native gateway process from the failed onboard
    pkill -f openshell-gateway 2>/dev/null || true
    docker rm -f nemoclaw-openshell-gateway 2>/dev/null || true
    sleep 3

    # Pre-start the gateway compat container with correct binary mounts.
    # The nemoclaw CLI detects the already-running gateway and skips
    # the broken bind-mount attempt. Host and container share $BIN_PATH,
    # so the same path is valid as a HOST bind-mount source here.
    echo "[Fix9] Pre-starting gateway container with correct binary mounts ($BIN_PATH)..."
    docker run -d --rm --name nemoclaw-openshell-gateway --network host \
      --volume "$BIN_PATH/openshell-gateway:/opt/nemoclaw/openshell-gateway:ro" \
      --volume "$BIN_PATH/openshell-sandbox:/tmp/nemoclaw-bin/openshell-sandbox:ro" \
      --volume /var/run/docker.sock:/var/run/docker.sock:rw \
      ubuntu:24.04 /opt/nemoclaw/openshell-gateway

    # Wait for gateway to become healthy
    echo "[Fix9] Waiting for gateway to be ready..."
    for _gw_i in $(seq 1 30); do
      if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
        echo "[Fix9] Gateway healthy"
        break
      fi
      sleep 2
    done

    # Retry the full installer — it detects the running gateway and skips starting one
    echo "[4/4] Retrying installer with gateway pre-started..."
    if eval "$_INSTALL_CMD"; then
      INSTALL_OK=true
    else
      if nemoclaw "${NEMOCLAW_SANDBOX_NAME:-retail-demo-assistant}" status >/dev/null 2>&1; then
        echo "[4/4] Sandbox exists after retry — continuing with post-install fixes."
        INSTALL_OK=true
      else
        echo "[4/4] NemoClaw installer failed again. Skipping post-install steps."
        INSTALL_OK=false
      fi
    fi
  fi
fi

# ─── Post-install: Telegram + Skill + SOUL/USER + connectivity fixes ──
if [ "$INSTALL_OK" = "true" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_USER_ID:-}" ]; then
  SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-retail-demo-assistant}"

  # ─── Resolve dynamic IPs ─────────────────────────────────────
  WORKSPACE_IP=$(get_workspace_ip)
  RETAIL_API_IP=$(get_retail_api_ip)
  echo "[IPs] Workspace: $WORKSPACE_IP, Retail API: $RETAIL_API_IP"

  # ─── Copy SKILL.md and SOUL.md for deployment ───────────────
  # /scripts is mounted read-only, so copy to /tmp for deployment.
  # The retail-api.js script reads the API URL from .env at runtime,
  # so no IP patching is needed in SKILL.md.
  echo "[Deploy] Copying SKILL.md and SOUL.md to /tmp..."
  cp /scripts/skills/retail-api/SKILL.md /tmp/SKILL.md
  cp /scripts/identity/SOUL.md /tmp/SOUL.md
  if [ -f /scripts/identity/AGENTS.md ]; then
    cp /scripts/identity/AGENTS.md /tmp/AGENTS.md
    echo "[Deploy] Custom AGENTS.md found, will override default."
  fi

  # Check if Telegram was already included during onboard (token was set).
  # If so, skip the expensive channels add + rebuild cycle.
  _HAS_TELEGRAM=$(nemoclaw "$SANDBOX_NAME" channels list 2>&1 | grep -c telegram || true)
  if [ "${_HAS_TELEGRAM:-0}" -gt "0" ]; then
    echo "[Telegram] Already configured during onboard, skipping rebuild."
  else
    # Register Telegram bridge provider with the OpenShell gateway.
    echo "[Telegram] Registering telegram bridge with OpenShell gateway..."
    nemoclaw "$SANDBOX_NAME" channels add telegram \
      && echo "[Telegram] Bridge registered"

    # Rebuild the sandbox image to link the Telegram provider.
    echo "[Telegram] Rebuilding sandbox to apply Telegram channel..."
    echo y | nemoclaw "$SANDBOX_NAME" rebuild \
      && echo "[Telegram] Sandbox rebuilt"
  fi

  # Patch sandboxes.json: add messagingChannels and providerCredentialHashes
  echo "[Telegram] Patching sandboxes.json..."
  node /scripts/init/patch-sandboxes.js

  # Wait for sandbox container to become ready (Docker driver)
  echo "[Sandbox] Waiting for sandbox container to become ready..."
  SANDBOX_CONTAINER=""
  for i in $(seq 1 60); do
    SANDBOX_CONTAINER=$(get_sandbox_container "$SANDBOX_NAME")
    if [ -n "$SANDBOX_CONTAINER" ]; then
      STATUS=$(docker inspect --format '{{.State.Status}}' "$SANDBOX_CONTAINER" 2>/dev/null || echo "")
      if [ "$STATUS" = "running" ]; then break; fi
    fi
    sleep 5
  done

  if [ -z "$SANDBOX_CONTAINER" ]; then
    echo "[ERROR] Sandbox container not found after 5 minutes."
    echo "[DEBUG] Docker containers:"
    docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null
  else
    echo "[Post-deploy] Sandbox container '$SANDBOX_CONTAINER' running. Applying connectivity fixes..."

    # ─── Fix 1: Update gateway provider URL to workspace IP ──────
    # The gateway's "compatible-endpoint" provider must point to this
    # container's real IP (not host.openshell.internal = 127.0.0.1).
    echo "[Post-deploy] Updating gateway provider URL..."
    openshell provider update compatible-endpoint -g nemoclaw \
      --config "OPENAI_BASE_URL=http://${WORKSPACE_IP}:${INFER_PORT}${OPENAI_PATH}" 2>&1 \
      && echo "[Post-deploy] Provider URL -> http://${WORKSPACE_IP}:${INFER_PORT}${OPENAI_PATH}"

    # ─── Fix 2: Add inference.local to sandbox /etc/hosts ────────
    # With Docker driver, the gateway runs on the workspace container.
    # Point inference.local to the workspace IP so the sandbox can reach it.
    echo "[Post-deploy] Adding inference.local to sandbox hosts..."
    docker exec "$SANDBOX_CONTAINER" \
      sh -c "echo '${WORKSPACE_IP} inference.local' >> /etc/hosts" 2>/dev/null \
      && echo "[Post-deploy] inference.local -> $WORKSPACE_IP"

    # ─── Fix 3a: Force-install nemoclaw plugin (exec tool) ────────
    echo "[Post-deploy] Force-installing nemoclaw plugin..."
    docker exec "$SANDBOX_CONTAINER" su -s /bin/sh sandbox -c \
      'openclaw plugins install /opt/nemoclaw --dangerously-force-unsafe-install --force 2>&1' \
      && echo "[Post-deploy] nemoclaw plugin installed (exec tool available)"

    # ─── Fix 3b: Patch openclaw.json (telegram, tools, workspace) ─
    echo "[Post-deploy] Patching openclaw.json..."
    cat /scripts/init/patch-openclaw.py | docker exec -i "$SANDBOX_CONTAINER" tee /tmp/_patch_openclaw.py > /dev/null

    SOUL_B64=$(base64 -w0 /tmp/SOUL.md)
    USER_B64=$(base64 -w0 /scripts/identity/USER.md)
    AGENTS_B64=""
    if [ -f /tmp/AGENTS.md ]; then
      AGENTS_B64=$(base64 -w0 /tmp/AGENTS.md)
    fi
    docker exec \
      -e TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
      -e TELEGRAM_USER_ID="$TELEGRAM_USER_ID" \
      -e CHAT_UI_URL="${CHAT_UI_URL:-}" \
      -e SOUL_B64="$SOUL_B64" \
      -e USER_B64="$USER_B64" \
      -e AGENTS_B64="$AGENTS_B64" \
      "$SANDBOX_CONTAINER" python3 /tmp/_patch_openclaw.py

    # ─── Fix 4: Install retail-api skill ─────────────────────────
    echo "[Post-deploy] Installing retail-api skill..."
    docker exec "$SANDBOX_CONTAINER" \
      mkdir -p /sandbox/.openclaw/skills/retail-api/scripts
    cat /tmp/SKILL.md | docker exec -i "$SANDBOX_CONTAINER" tee /sandbox/.openclaw/skills/retail-api/SKILL.md > /dev/null

    # Deploy retail-api.js CLI wrapper
    cat /scripts/skills/retail-api/scripts/retail-api.js | \
      docker exec -i "$SANDBOX_CONTAINER" tee /sandbox/.openclaw/skills/retail-api/scripts/retail-api.js > /dev/null

    # Write .env with the API URL so retail-api.js knows where to connect.
    # [Fix #4] Exec tool processes can ONLY reach 10.200.0.1 (veth bridge).
    # The relay on 10.200.0.1:8001 (Fix #5 below) forwards to the real API.
    docker exec "$SANDBOX_CONTAINER" \
      sh -c "echo 'RETAIL_API_URL=http://10.200.0.1:8001' > /sandbox/.openclaw/skills/retail-api/.env"

    # Also install to /home/.openclaw/skills/ — newer agent versions read from here
    docker exec "$SANDBOX_CONTAINER" \
      mkdir -p /home/.openclaw/skills/retail-api/scripts
    cat /tmp/SKILL.md | docker exec -i "$SANDBOX_CONTAINER" tee /home/.openclaw/skills/retail-api/SKILL.md > /dev/null
    cat /scripts/skills/retail-api/scripts/retail-api.js | \
      docker exec -i "$SANDBOX_CONTAINER" tee /home/.openclaw/skills/retail-api/scripts/retail-api.js > /dev/null
    docker exec "$SANDBOX_CONTAINER" \
      sh -c "echo 'RETAIL_API_URL=http://10.200.0.1:8001' > /home/.openclaw/skills/retail-api/.env"

    # Fix ownership: files created as root, but openclaw runs as 'sandbox'
    docker exec "$SANDBOX_CONTAINER" sh -c \
      "chown -R sandbox:sandbox /sandbox/.openclaw/skills/ /sandbox/.openclaw/workspace/ 2>/dev/null; chmod -R a+r /sandbox/.openclaw/skills/ 2>/dev/null"

    DEPLOYED_URL=$(docker exec "$SANDBOX_CONTAINER" \
      grep "retail API at" /sandbox/.openclaw/skills/retail-api/SKILL.md 2>/dev/null || echo "")
    echo "[Post-deploy] Skill installed: $DEPLOYED_URL"

    # ─── Fix 5: Apply network policy with retail API access ──────
    echo "[Post-deploy] Applying network policy..."
    cp /scripts/policies/policy.yaml /tmp/policy-resolved.yaml
    for _pa in $(seq 1 5); do
      if openshell policy set -g nemoclaw --policy /tmp/policy-resolved.yaml "$SANDBOX_NAME" 2>&1; then
        echo "[Post-deploy] Policy applied (attempt $_pa)"
        break
      fi
      echo "[Post-deploy] Policy apply failed (attempt $_pa/5), retrying..."
      sleep 5
    done

    # ─── Fix 5b: TCP relay on 10.200.0.1 inside sandbox ─────────
    # [Fix #4/#5] Exec tool child processes run in a restricted network
    # namespace and can ONLY reach 10.200.0.1 (the veth bridge).
    # Start a Python TCP relay on 10.200.0.1:8001 forwarding to the workspace's
    # retail API proxy (WORKSPACE_IP:8001).
    # NOTE: socat is NOT available in the sandbox — use Python instead.
    echo "[Post-deploy] Starting TCP relay on 10.200.0.1:8001 in sandbox..."
    docker exec -d "$SANDBOX_CONTAINER" python3 -c "
import socket, threading, sys
def relay(s,d):
    try:
        while True:
            b=s.recv(65536)
            if not b: break
            d.sendall(b)
    except: pass
    finally: s.close(); d.close()
def handle(c):
    d=socket.socket()
    d.connect(('${WORKSPACE_IP}',8001))
    threading.Thread(target=relay,args=(c,d),daemon=True).start()
    threading.Thread(target=relay,args=(d,c),daemon=True).start()
s=socket.socket()
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('10.200.0.1',8001))
s.listen(32)
while True:
    c,_=s.accept()
    threading.Thread(target=handle,args=(c,),daemon=True).start()
" 2>/dev/null \
      && echo "[Post-deploy] TCP relay: 10.200.0.1:8001 -> ${WORKSPACE_IP}:8001"
    sleep 2
    # Verify relay is listening
    if docker exec "$SANDBOX_CONTAINER" ss -tlnp 2>/dev/null | grep -q '10.200.0.1:8001'; then
      echo "[Post-deploy] Retail API relay verified (10.200.0.1:8001)"
    else
      echo "[Post-deploy] WARNING: Retail API relay failed to start"
    fi

    # ─── Fix 6: Wait for hot-reload and re-apply ─────────────────
    echo "[Post-deploy] Waiting for openclaw hot-reload..."
    sleep 10

    docker exec "$SANDBOX_CONTAINER" \
      env TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
          TELEGRAM_USER_ID="$TELEGRAM_USER_ID" \
          CHAT_UI_URL="${CHAT_UI_URL:-}" \
      python3 /tmp/_patch_openclaw.py

    # ─── Fix 7: Restart openclaw with kill -9 ────────────────────
    # [Fix #7] SIGUSR1 (in-process restart) doesn't clean up Telegram
    # poller threads, causing "refusing duplicate poller" errors.
    # kill -9 the openclaw process; PID 1 (openshell-sandbox) auto-restarts it.
    echo "[Post-deploy] Restarting openclaw (kill -9 for clean Telegram poller)..."
    docker exec "$SANDBOX_CONTAINER" \
      sh -c 'OCPID=$(pgrep -f "openclaw" | head -1); if [ -n "$OCPID" ] && [ "$OCPID" != "1" ]; then kill -9 "$OCPID"; echo "Killed openclaw PID $OCPID"; else echo "openclaw PID not found or is PID 1, skipping"; fi'
    sleep 5

    # ─── Fix 7: Verify inference end-to-end ──────────────────────
    echo "[Post-deploy] Verifying inference connectivity..."
    for attempt in $(seq 1 6); do
      # Use the gateway proxy (10.200.0.1:3128) since inference.local
      # is only routable through the proxy from inside the sandbox.
      MODELS=$(docker exec "$SANDBOX_CONTAINER" \
        curl -sk --max-time 10 \
        -x http://10.200.0.1:3128 \
        https://inference.local/v1/models 2>/dev/null || echo "")
      if echo "$MODELS" | grep -q "object"; then
        echo "[Post-deploy] Inference OK (attempt $attempt)"
        break
      fi
      echo "[Post-deploy] Inference not ready (attempt $attempt/6), retrying..."
      sleep 10
    done
    if ! echo "$MODELS" | grep -q "object"; then
      echo "[Post-deploy] WARNING: Inference verification failed."
      echo "[Post-deploy] Check: socat ${INFER_PORT}? vLLM up? DNS resolving?"
    fi

    echo "[Post-deploy] All fixes applied."
  fi

  # Print the dashboard URL with auth token
  DASHBOARD_TOKEN=$(docker exec "$SANDBOX_CONTAINER" \
    python3 -c "import json; c=json.load(open('/sandbox/.openclaw/openclaw.json')); print(c['gateway']['auth']['token'])" 2>/dev/null || echo "")
  if [ -n "$DASHBOARD_TOKEN" ] && [ -n "${CHAT_UI_URL:-}" ]; then
    echo "[Dashboard URL] ${CHAT_UI_URL%/}/#token=${DASHBOARD_TOKEN}"
  fi
fi

echo "Onboard complete. Container staying alive."
exec sleep infinity
