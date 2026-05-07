#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw sandbox entrypoint for Hermes Agent.
#
# Mirrors scripts/nemoclaw-start.sh (OpenClaw) but launches `hermes gateway
# start` instead of `openclaw gateway run`. Key differences:
#   - No device-pairing auto-pair watcher (Hermes has no browser pairing)
#   - Config is YAML (config.yaml + .env) not JSON (openclaw.json)
#   - Gateway listens on internal port 18642, socat forwards to 8642
#
# SECURITY: The gateway runs as a separate user so the sandboxed agent cannot
# kill it or restart it with a tampered config. Config hash is verified at
# startup to detect tampering.

set -euo pipefail

# Harden: limit process count to prevent fork bombs
if ! ulimit -Su 512 2>/dev/null; then
  echo "[SECURITY] Could not set soft nproc limit (container runtime may restrict ulimit)" >&2
fi
if ! ulimit -Hu 512 2>/dev/null; then
  echo "[SECURITY] Could not set hard nproc limit (container runtime may restrict ulimit)" >&2
fi

# SECURITY: Lock down PATH
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── Drop unnecessary Linux capabilities ──────────────────────────
if [ "${NEMOCLAW_CAPS_DROPPED:-}" != "1" ] && command -v capsh >/dev/null 2>&1; then
  if capsh --has-p=cap_setpcap 2>/dev/null; then
    export NEMOCLAW_CAPS_DROPPED=1
    exec capsh \
      --drop=cap_net_raw,cap_dac_override,cap_sys_chroot,cap_fsetid,cap_setfcap,cap_mknod,cap_audit_write,cap_net_bind_service \
      -- -c 'exec /usr/local/bin/nemoclaw-start "$@"' -- "$@"
  else
    echo "[SECURITY] CAP_SETPCAP not available — runtime already restricts capabilities" >&2
  fi
elif [ "${NEMOCLAW_CAPS_DROPPED:-}" != "1" ]; then
  echo "[SECURITY WARNING] capsh not available — running with default capabilities" >&2
fi

# Normalize the self-wrapper bootstrap (same as OpenClaw entrypoint).
if [ "${1:-}" = "env" ]; then
  _raw_args=("$@")
  _self_wrapper_index=""
  for ((i = 1; i < ${#_raw_args[@]}; i += 1)); do
    case "${_raw_args[$i]}" in
      *=*) ;;
      nemoclaw-start | /usr/local/bin/nemoclaw-start)
        _self_wrapper_index="$i"
        break
        ;;
      *)
        break
        ;;
    esac
  done
  if [ -n "$_self_wrapper_index" ]; then
    for ((i = 1; i < _self_wrapper_index; i += 1)); do
      export "${_raw_args[$i]}"
    done
    set -- "${_raw_args[@]:$((_self_wrapper_index + 1))}"
  fi
fi

case "${1:-}" in
  nemoclaw-start | /usr/local/bin/nemoclaw-start) shift ;;
esac
NEMOCLAW_CMD=("$@")
CHAT_UI_URL="${CHAT_UI_URL:-http://127.0.0.1:8642}"
PUBLIC_PORT=8642
# Hermes binds to 127.0.0.1 regardless of config (upstream bug).
# Run it on an internal port and use socat to expose on PUBLIC_PORT.
INTERNAL_PORT=18642
HERMES="$(command -v hermes)" # Resolve once, use absolute path everywhere

# Hermes writes state files (PID, state.db, .channel_directory) directly into
# HERMES_HOME. We cannot point it at the immutable /sandbox/.hermes dir.
# Instead: verify integrity of the immutable source, then copy config to the
# writable .hermes-data dir so Hermes can coexist with its own state files.
HERMES_IMMUTABLE="/sandbox/.hermes"
HERMES_WRITABLE="/sandbox/.hermes-data"

# ── Config integrity check ──────────────────────────────────────
verify_config_integrity() {
  local hash_file="${HERMES_IMMUTABLE}/.config-hash"
  if [ ! -f "$hash_file" ]; then
    echo "[SECURITY] Config hash file missing — refusing to start without integrity verification" >&2
    return 1
  fi
  if ! (cd "${HERMES_IMMUTABLE}" && sha256sum -c "$hash_file" --status 2>/dev/null); then
    echo "[SECURITY] Hermes config integrity check FAILED — config may have been tampered with" >&2
    return 1
  fi
}

# Copy verified immutable config into the writable HERMES_HOME so the
# gateway process can read it alongside its own state files.
deploy_config_to_writable() {
  # When running as root, use gosu to write as sandbox user (owner of .hermes-data).
  if [ "$(id -u)" -eq 0 ]; then
    gosu sandbox cp "${HERMES_IMMUTABLE}/config.yaml" "${HERMES_WRITABLE}/config.yaml"
    gosu sandbox cp "${HERMES_IMMUTABLE}/.env" "${HERMES_WRITABLE}/.env"
  else
    cp "${HERMES_IMMUTABLE}/config.yaml" "${HERMES_WRITABLE}/config.yaml"
    cp "${HERMES_IMMUTABLE}/.env" "${HERMES_WRITABLE}/.env"
  fi
  chmod 600 "${HERMES_WRITABLE}/config.yaml" "${HERMES_WRITABLE}/.env" 2>/dev/null || true
  echo "[config] Deployed verified config to ${HERMES_WRITABLE}" >&2
}

install_configure_guard() {
  local marker_begin="# nemoclaw-configure-guard begin"
  local marker_end="# nemoclaw-configure-guard end"
  local snippet
  read -r -d '' snippet <<'GUARD' || true
# nemoclaw-configure-guard begin
hermes() {
  case "$1" in
    setup|doctor)
      echo "Error: 'hermes $1' cannot modify config inside the sandbox." >&2
      echo "The sandbox config is read-only (Landlock enforced) for security." >&2
      echo "" >&2
      echo "To change your configuration, exit the sandbox and run:" >&2
      echo "  nemoclaw onboard --resume" >&2
      return 1
      ;;
  esac
  command hermes "$@"
}
# nemoclaw-configure-guard end
GUARD

  for rc_file in "${_SANDBOX_HOME}/.bashrc" "${_SANDBOX_HOME}/.profile"; do
    if [ -f "$rc_file" ] && grep -qF "$marker_begin" "$rc_file" 2>/dev/null; then
      local tmp
      tmp="$(mktemp)"
      awk -v b="$marker_begin" -v e="$marker_end" \
        '$0==b{s=1;next} $0==e{s=0;next} !s' "$rc_file" >"$tmp"
      printf '%s\n' "$snippet" >>"$tmp"
      cat "$tmp" >"$rc_file"
      rm -f "$tmp"
    elif [ -w "$rc_file" ] || [ -w "$(dirname "$rc_file")" ]; then
      printf '\n%s\n' "$snippet" >>"$rc_file"
    fi
  done
}

validate_hermes_symlinks() {
  local entry name target expected
  for entry in /sandbox/.hermes/*; do
    [ -L "$entry" ] || continue
    name="$(basename "$entry")"
    target="$(readlink -f "$entry" 2>/dev/null || true)"
    expected="/sandbox/.hermes-data/$name"
    if [ "$target" != "$expected" ]; then
      echo "[SECURITY] Symlink $entry points to unexpected target: $target (expected $expected)" >&2
      return 1
    fi
  done
}

harden_hermes_symlinks() {
  local entry hardened failed
  hardened=0
  failed=0

  if ! command -v chattr >/dev/null 2>&1; then
    echo "[SECURITY] chattr not available — relying on DAC + Landlock for .hermes hardening" >&2
    return 0
  fi

  if chattr +i /sandbox/.hermes 2>/dev/null; then
    hardened=$((hardened + 1))
  else
    failed=$((failed + 1))
  fi

  for entry in /sandbox/.hermes/*; do
    [ -L "$entry" ] || continue
    if chattr +i "$entry" 2>/dev/null; then
      hardened=$((hardened + 1))
    else
      failed=$((failed + 1))
    fi
  done

  if [ "$failed" -gt 0 ]; then
    echo "[SECURITY] Immutable hardening applied to $hardened path(s); $failed path(s) could not be hardened — continuing with DAC + Landlock" >&2
  elif [ "$hardened" -gt 0 ]; then
    echo "[SECURITY] Immutable hardening applied to /sandbox/.hermes and validated symlinks" >&2
  fi
}

_has_outlook_channel() {
  # Primary: OUTLOOK_CLIENT_ID is injected by OpenShell providers at runtime,
  # making it a reliable signal that the Outlook channel was configured.
  # Secondary: NEMOCLAW_MESSAGING_CHANNELS_B64 (baked at build time, may not
  # be present if OpenShell doesn't forward Docker ENV vars).
  [ -n "${OUTLOOK_CLIENT_ID:-}" ] \
    || echo "${NEMOCLAW_MESSAGING_CHANNELS_B64:-W10=}" \
    | python3 -c "import sys,base64,json; d=json.loads(base64.b64decode(sys.stdin.read().strip())); sys.exit(0 if 'outlook' in d else 1)" 2>/dev/null
}

configure_messaging_channels() {
  # Channel entries are baked into config.yaml at image build time via
  # NEMOCLAW_MESSAGING_CHANNELS_B64. Placeholder tokens flow through to
  # the L7 proxy for rewriting at egress.
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -n "${DISCORD_BOT_TOKEN:-}" ] \
    || [ -n "${SLACK_BOT_TOKEN:-}" ] || _has_outlook_channel || return 0

  echo "[channels] Messaging channels active (baked at build time):" >&2
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && echo "[channels]   telegram" >&2
  [ -n "${DISCORD_BOT_TOKEN:-}" ] && echo "[channels]   discord" >&2
  [ -n "${SLACK_BOT_TOKEN:-}" ] && echo "[channels]   slack" >&2
  _has_outlook_channel && echo "[channels]   outlook (bridge)" >&2
  return 0
}

print_dashboard_urls() {
  local local_url
  local_url="http://127.0.0.1:${PUBLIC_PORT}/v1"
  echo "[gateway] Hermes API: ${local_url}" >&2
  echo "[gateway] Health:     ${local_url%/v1}/health" >&2
  echo "[gateway] Connect any OpenAI-compatible frontend to this endpoint." >&2
}

# ── socat forwarder ──────────────────────────────────────────────
# Hermes API server binds to 127.0.0.1 regardless of config (upstream bug).
# OpenShell needs the port accessible on 0.0.0.0 for port forwarding.
# socat bridges 0.0.0.0:PUBLIC_PORT → 127.0.0.1:INTERNAL_PORT.
SOCAT_PID=""
start_socat_forwarder() {
  if ! command -v socat >/dev/null 2>&1; then
    echo "[gateway] socat not available — port forwarding from host may not work" >&2
    return
  fi
  local attempts=0
  while [ "$attempts" -lt 30 ]; do
    if ss -tln 2>/dev/null | grep -q "127.0.0.1:${INTERNAL_PORT}"; then
      break
    fi
    sleep 1
    attempts=$((attempts + 1))
  done
  nohup socat TCP-LISTEN:"${PUBLIC_PORT}",bind=0.0.0.0,fork,reuseaddr \
    TCP:127.0.0.1:"${INTERNAL_PORT}" >/dev/null 2>&1 &
  SOCAT_PID=$!
  echo "[gateway] socat forwarder 0.0.0.0:${PUBLIC_PORT} → 127.0.0.1:${INTERNAL_PORT} (pid $SOCAT_PID)" >&2
}

# ── URL-decode proxy ─────────────────────────────────────────────
# Python HTTP clients (httpx) URL-encode colons in paths, breaking
# OpenShell's openshell:resolve:env: placeholder pattern. This proxy
# sits between the Hermes process and the OpenShell proxy, URL-decoding
# paths so the L7 proxy recognizes the placeholders.
DECODE_PROXY_PID=""
DECODE_PROXY_PORT=3129
start_decode_proxy() {
  nohup python3 /usr/local/bin/nemoclaw-decode-proxy >/dev/null 2>&1 &
  DECODE_PROXY_PID=$!
  # Wait for it to start listening
  local attempts=0
  while [ "$attempts" -lt 10 ]; do
    if ss -tln 2>/dev/null | grep -q "127.0.0.1:${DECODE_PROXY_PORT}"; then
      echo "[gateway] decode-proxy listening on 127.0.0.1:${DECODE_PROXY_PORT} (pid $DECODE_PROXY_PID)" >&2
      return
    fi
    sleep 0.5
    attempts=$((attempts + 1))
  done
  echo "[gateway] decode-proxy failed to start — placeholder rewriting may not work" >&2
}

# Forward SIGTERM/SIGINT to child processes for graceful shutdown.
OUTLOOK_BRIDGE_PID=""
MS_GRAPH_SIDECAR_PID=""

cleanup() {
  echo "[gateway] received signal, forwarding to children..." >&2
  local gateway_status=0
  kill -TERM "$GATEWAY_PID" 2>/dev/null || true
  [ -n "${SOCAT_PID:-}" ] && kill -TERM "$SOCAT_PID" 2>/dev/null || true
  [ -n "${DECODE_PROXY_PID:-}" ] && kill -TERM "$DECODE_PROXY_PID" 2>/dev/null || true
  [ -n "${MS_GRAPH_SIDECAR_PID:-}" ] && kill -TERM "$MS_GRAPH_SIDECAR_PID" 2>/dev/null || true
  [ -n "${OUTLOOK_BRIDGE_PID:-}" ] && kill -TERM "$OUTLOOK_BRIDGE_PID" 2>/dev/null || true
  wait "$GATEWAY_PID" 2>/dev/null || gateway_status=$?
  exit "$gateway_status"
}

start_ms_graph_sidecar() {
  _has_outlook_channel || return 0
  local sidecar_bin="/usr/local/bin/ms-graph-sidecar"
  [ -f "$sidecar_bin" ] || {
    echo "[ms-graph-sidecar] binary not found at ${sidecar_bin}, skipping" >&2
    return 0
  }
  # TOKEN_MANAGER_HOST is baked into the image as a Docker ARG/ENV (Phoenix pattern).
  # The sidecar uses trust_env=True so it inherits HTTP_PROXY=http://10.200.0.1:3128
  # from this script's exported environment. All requests (Graph API and token manager)
  # flow through the OpenShell L7 proxy directly, which attributes them to the sidecar
  # binary path for policy enforcement. No decode-proxy hop needed here.
  local sidecar_env
  sidecar_env="SIDECAR_LISTEN_HOST=${SIDECAR_LISTEN_ADDR} SIDECAR_LISTEN_PORT=${SIDECAR_PORT}"
  if [ "$(id -u)" -eq 0 ]; then
    # shellcheck disable=SC2086
    nohup env ${sidecar_env} gosu ms-graph-proxy "$sidecar_bin" >>/tmp/ms-graph-sidecar.log 2>&1 &
  else
    # shellcheck disable=SC2086
    nohup env ${sidecar_env} "$sidecar_bin" >>/tmp/ms-graph-sidecar.log 2>&1 &
  fi
  MS_GRAPH_SIDECAR_PID=$!
  echo "[ms-graph-sidecar] started (pid ${MS_GRAPH_SIDECAR_PID})" >&2
  # Wait for sidecar to be listening before bridge starts
  local attempts=0
  while [ "$attempts" -lt 15 ]; do
    if ss -tln 2>/dev/null | grep -q "${SIDECAR_LISTEN_ADDR}:${SIDECAR_PORT}"; then
      echo "[ms-graph-sidecar] listening on ${SIDECAR_LISTEN_ADDR}:${SIDECAR_PORT}" >&2
      return 0
    fi
    sleep 1
    attempts=$((attempts + 1))
  done
  echo "[ms-graph-sidecar] WARNING: sidecar may not be ready yet (${SIDECAR_LISTEN_ADDR}:${SIDECAR_PORT} not detected)" >&2
}

start_outlook_bridge() {
  if ! _has_outlook_channel; then
    return 0
  fi
  [ -f /usr/local/lib/nemoclaw-bridges/outlook/outlook-bridge.py ] || {
    echo "[outlook-bridge] bridge script not found, skipping" >&2
    return 0
  }
  local bridge_env
  # MS_GRAPH_SIDECAR_URL routes Graph API calls through the credential sidecar on
  # loopback (plain HTTP). The sidecar injects the live token and forwards to
  # graph.microsoft.com over HTTPS via the decode proxy → L7 proxy chain.
  # HTTPS_PROXY/HTTP_PROXY remain set for any other external HTTP traffic.
  # NO_PROXY ensures the local Hermes gateway is always reached directly.
  bridge_env="HERMES_HOME=${HERMES_WRITABLE} \
    MS_GRAPH_SIDECAR_URL=http://127.0.0.1:${SIDECAR_PORT} \
    HTTPS_PROXY=http://127.0.0.1:${DECODE_PROXY_PORT} \
    HTTP_PROXY=http://127.0.0.1:${DECODE_PROXY_PORT} \
    https_proxy=http://127.0.0.1:${DECODE_PROXY_PORT} \
    http_proxy=http://127.0.0.1:${DECODE_PROXY_PORT} \
    NO_PROXY=localhost,127.0.0.1,::1 \
    no_proxy=localhost,127.0.0.1,::1"
  if [ "$(id -u)" -eq 0 ]; then
    # shellcheck disable=SC2086
    nohup env ${bridge_env} gosu sandbox python3 /usr/local/lib/nemoclaw-bridges/outlook/outlook-bridge.py \
      >>/tmp/outlook-bridge.log 2>&1 &
  else
    # shellcheck disable=SC2086
    nohup env ${bridge_env} python3 /usr/local/lib/nemoclaw-bridges/outlook/outlook-bridge.py \
      >>/tmp/outlook-bridge.log 2>&1 &
  fi
  OUTLOOK_BRIDGE_PID=$!
  echo "[outlook-bridge] started (pid ${OUTLOOK_BRIDGE_PID})" >&2
}

# ── Proxy environment ────────────────────────────────────────────
PROXY_HOST="${NEMOCLAW_PROXY_HOST:-10.200.0.1}"
PROXY_PORT="${NEMOCLAW_PROXY_PORT:-3128}"
_PROXY_URL="http://${PROXY_HOST}:${PROXY_PORT}"
_NO_PROXY_VAL="localhost,127.0.0.1,::1,${PROXY_HOST}"
# Sidecar bind address and port — consumers always connect via 127.0.0.1 (loopback)
SIDECAR_PORT="${SIDECAR_LISTEN_PORT:-8766}"
SIDECAR_LISTEN_ADDR="${SIDECAR_LISTEN_HOST:-127.0.0.1}"
export HTTP_PROXY="$_PROXY_URL"
export HTTPS_PROXY="$_PROXY_URL"
export NO_PROXY="$_NO_PROXY_VAL"
export http_proxy="$_PROXY_URL"
export https_proxy="$_PROXY_URL"
export no_proxy="$_NO_PROXY_VAL"
# Export Outlook channel placeholder so _has_outlook_channel detects it at
# runtime even when NEMOCLAW_MESSAGING_CHANNELS_B64 was baked without Outlook
# (e.g., rebuild without env sourced). The L7 proxy rewrites the placeholder at
# egress; a non-empty value here means "provider is expected to be configured."
export OUTLOOK_CLIENT_ID="openshell:resolve:env:OUTLOOK_CLIENT_ID"
export OUTLOOK_SESSION_UUID="openshell:resolve:env:OUTLOOK_SESSION_UUID"
export MS_GRAPH_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"

_PROXY_MARKER_BEGIN="# nemoclaw-proxy-config begin"
_PROXY_MARKER_END="# nemoclaw-proxy-config end"
_PROXY_SNIPPET="${_PROXY_MARKER_BEGIN}
export HTTP_PROXY=\"$_PROXY_URL\"
export HTTPS_PROXY=\"$_PROXY_URL\"
export NO_PROXY=\"$_NO_PROXY_VAL\"
export http_proxy=\"$_PROXY_URL\"
export https_proxy=\"$_PROXY_URL\"
export no_proxy=\"$_NO_PROXY_VAL\"
export HERMES_HOME=\"${HERMES_WRITABLE}\"
export SLACK_BOT_TOKEN=\"openshell:resolve:env:SLACK_BOT_TOKEN\"
export GITHUB_TOKEN=\"openshell:resolve:env:GITHUB_TOKEN\"
export MS_GRAPH_SIDECAR_URL=\"http://127.0.0.1:${SIDECAR_PORT}\"
${_PROXY_MARKER_END}"

if [ "$(id -u)" -eq 0 ]; then
  _SANDBOX_HOME=$(getent passwd sandbox 2>/dev/null | cut -d: -f6)
  _SANDBOX_HOME="${_SANDBOX_HOME:-/sandbox}"
else
  _SANDBOX_HOME="${HOME:-/sandbox}"
fi

_write_proxy_snippet() {
  local target="$1"
  if [ -f "$target" ] && grep -qF "$_PROXY_MARKER_BEGIN" "$target" 2>/dev/null; then
    local tmp
    tmp="$(mktemp)"
    awk -v b="$_PROXY_MARKER_BEGIN" -v e="$_PROXY_MARKER_END" \
      '$0==b{s=1;next} $0==e{s=0;next} !s' "$target" >"$tmp"
    printf '%s\n' "$_PROXY_SNIPPET" >>"$tmp"
    cat "$tmp" >"$target"
    rm -f "$tmp"
    return 0
  fi
  printf '\n%s\n' "$_PROXY_SNIPPET" >>"$target"
}

# Write proxy snippet — may fail after capsh drops cap_dac_override
# (root can no longer write sandbox-owned files). Non-fatal.
if [ -w "$_SANDBOX_HOME" ]; then
  _write_proxy_snippet "${_SANDBOX_HOME}/.bashrc" 2>/dev/null || true
  _write_proxy_snippet "${_SANDBOX_HOME}/.profile" 2>/dev/null || true
fi

# ── Main ─────────────────────────────────────────────────────────

echo 'Setting up NemoClaw (Hermes)...' >&2

# ── Non-root fallback ──────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  echo "[gateway] Running as non-root (uid=$(id -u)) — privilege separation disabled" >&2
  export HOME=/sandbox
  export HERMES_HOME="${HERMES_WRITABLE}"

  if ! verify_config_integrity; then
    echo "[SECURITY] Config integrity check failed — refusing to start (non-root mode)" >&2
    exit 1
  fi
  deploy_config_to_writable
  install_configure_guard
  configure_messaging_channels

  if [ ${#NEMOCLAW_CMD[@]} -gt 0 ]; then
    exec "${NEMOCLAW_CMD[@]}"
  fi

  touch /tmp/gateway.log
  chmod 600 /tmp/gateway.log

  # Prepare ATIF telemetry directory (ephemeral, writable by the current user).
  mkdir -p /tmp/atif
  # Detect NeMo-Flow by package availability — more reliable than env var inheritance.
  if python3 -c "import nemo_flow" 2>/dev/null; then
    NEMO_FLOW_ENABLED=1
  else
    NEMO_FLOW_ENABLED=0
  fi
  {
    echo "[nemo-flow] NEMO_FLOW_ENABLED=${NEMO_FLOW_ENABLED}"
    echo "[nemo-flow] PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT:-<unset>}"
  } | tee -a /tmp/gateway.log >&2
  PHOENIX_OPENINFERENCE_ENABLED=0
  [ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ] && PHOENIX_OPENINFERENCE_ENABLED=1
  echo "[nemo-flow] PHOENIX_OPENINFERENCE_ENABLED=${PHOENIX_OPENINFERENCE_ENABLED}" | tee -a /tmp/gateway.log >&2

  start_decode_proxy
  export NEMOCLAW_DECODE_PROXY_DEBUG=1
  HERMES_HOME="${HERMES_WRITABLE}" \
    HTTPS_PROXY="http://127.0.0.1:${DECODE_PROXY_PORT}" \
    HTTP_PROXY="http://127.0.0.1:${DECODE_PROXY_PORT}" \
    https_proxy="http://127.0.0.1:${DECODE_PROXY_PORT}" \
    http_proxy="http://127.0.0.1:${DECODE_PROXY_PORT}" \
    HERMES_NEMO_FLOW_ENABLED="${NEMO_FLOW_ENABLED:-0}" \
    HERMES_NEMO_FLOW_ATIF_DIR="/tmp/atif" \
    HERMES_NEMO_FLOW_ACG_ENABLED="0" \
    HERMES_NEMO_FLOW_OPENINFERENCE_ENABLED="${PHOENIX_OPENINFERENCE_ENABLED}" \
    HERMES_NEMO_FLOW_OPENINFERENCE_TRANSPORT="http_binary" \
    HERMES_NEMO_FLOW_OPENINFERENCE_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-}" \
    HERMES_NEMO_FLOW_OPENINFERENCE_SERVICE_NAME="hermes-agent" \
    API_SERVER_KEY="nemoclaw-internal" \
    nohup "$HERMES" gateway run >>/tmp/gateway.log 2>&1 &
  GATEWAY_PID=$!
  echo "[gateway] hermes gateway launched (pid $GATEWAY_PID)" >&2
  trap cleanup SIGTERM SIGINT
  start_socat_forwarder
  start_ms_graph_sidecar
  start_outlook_bridge
  print_dashboard_urls

  wait "$GATEWAY_PID"
  exit $?
fi

# ── Root path (full privilege separation via gosu) ─────────────

verify_config_integrity
deploy_config_to_writable
install_configure_guard
configure_messaging_channels

if [ ${#NEMOCLAW_CMD[@]} -gt 0 ]; then
  exec gosu sandbox "${NEMOCLAW_CMD[@]}"
fi

# SECURITY: Protect gateway log from sandbox user tampering
touch /tmp/gateway.log
chown gateway:gateway /tmp/gateway.log
chmod 600 /tmp/gateway.log

# Prepare ATIF telemetry directory. Root pre-creates and chowns so the
# gateway user (launched via gosu below) can write to it.
mkdir -p /tmp/atif
chown gateway:gateway /tmp/atif
# Detect NeMo-Flow by package availability — more reliable than env var inheritance.
if python3 -c "import nemo_flow" 2>/dev/null; then
  NEMO_FLOW_ENABLED=1
else
  NEMO_FLOW_ENABLED=0
fi
{
  echo "[nemo-flow] NEMO_FLOW_ENABLED=${NEMO_FLOW_ENABLED}"
  echo "[nemo-flow] PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT:-<unset>}"
} | tee -a /tmp/gateway.log >&2
PHOENIX_OPENINFERENCE_ENABLED=0
[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ] && PHOENIX_OPENINFERENCE_ENABLED=1
echo "[nemo-flow] PHOENIX_OPENINFERENCE_ENABLED=${PHOENIX_OPENINFERENCE_ENABLED}" | tee -a /tmp/gateway.log >&2

# Verify ALL symlinks in .hermes point to expected .hermes-data targets.
validate_hermes_symlinks

# Lock .hermes directory after validation.
harden_hermes_symlinks

# Start the gateway as the 'gateway' user.
start_decode_proxy
export NEMOCLAW_DECODE_PROXY_DEBUG=1
HERMES_HOME="${HERMES_WRITABLE}" \
  HTTPS_PROXY="http://127.0.0.1:${DECODE_PROXY_PORT}" \
  HTTP_PROXY="http://127.0.0.1:${DECODE_PROXY_PORT}" \
  https_proxy="http://127.0.0.1:${DECODE_PROXY_PORT}" \
  http_proxy="http://127.0.0.1:${DECODE_PROXY_PORT}" \
  HERMES_NEMO_FLOW_ENABLED="${NEMO_FLOW_ENABLED:-0}" \
  HERMES_NEMO_FLOW_ATIF_DIR="/tmp/atif" \
  HERMES_NEMO_FLOW_ACG_ENABLED="0" \
  HERMES_NEMO_FLOW_OPENINFERENCE_ENABLED="${PHOENIX_OPENINFERENCE_ENABLED}" \
  HERMES_NEMO_FLOW_OPENINFERENCE_TRANSPORT="http_binary" \
  HERMES_NEMO_FLOW_OPENINFERENCE_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-}" \
  HERMES_NEMO_FLOW_OPENINFERENCE_SERVICE_NAME="hermes-agent" \
  API_SERVER_KEY="nemoclaw-internal" \
  nohup gosu gateway "$HERMES" gateway run >>/tmp/gateway.log 2>&1 &
GATEWAY_PID=$!
echo "[gateway] hermes gateway launched as 'gateway' user (pid $GATEWAY_PID)" >&2
trap cleanup SIGTERM SIGINT
start_socat_forwarder
start_ms_graph_sidecar
start_outlook_bridge
print_dashboard_urls

# Keep container running by waiting on the gateway process.
wait "$GATEWAY_PID"
