#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw sandbox entrypoint for Hermes Agent (community example).
#
# This example keeps the immutable + writable HERMES split:
#   /sandbox/.hermes       — root-owned, immutable config (config.yaml, .env, hash, symlinks)
#   /sandbox/.hermes-data  — sandbox-owned, writable runtime state + bundled skills/SOUL/plugins
#
# Security primitives (capability drop, atomic rc-file rewrite, cleanup trap,
# config integrity verify, validate/harden config symlinks) are sourced from
# the shared sandbox-init.sh library so this example automatically inherits
# upstream NemoClaw security fixes.

set -euo pipefail

# ── Source shared sandbox initialisation library ─────────────────
# Single source of truth for security-sensitive primitives. Mirrors
# upstream NemoClaw agents/hermes/start.sh resolution.
# Installed location (container): /usr/local/lib/nemoclaw/sandbox-init.sh
# Dev fallback: scripts/lib/sandbox-init.sh relative to this script.
_SANDBOX_INIT="/usr/local/lib/nemoclaw/sandbox-init.sh"
if [ ! -f "$_SANDBOX_INIT" ]; then
  _SANDBOX_INIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../scripts/lib/sandbox-init.sh"
fi
# shellcheck source=../../scripts/lib/sandbox-init.sh
source "$_SANDBOX_INIT"

# Harden: limit process count to prevent fork bombs
if ! ulimit -Su 512 2>/dev/null; then
  echo "[SECURITY] Could not set soft nproc limit (container runtime may restrict ulimit)" >&2
fi
if ! ulimit -Hu 512 2>/dev/null; then
  echo "[SECURITY] Could not set hard nproc limit (container runtime may restrict ulimit)" >&2
fi

# SECURITY: Lock down PATH
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── Early stderr/stdout capture ──────────────────────────────────
# Capture all entrypoint output to /tmp/nemoclaw-start.log so startup
# failures before /tmp/gateway.log exists are still diagnosable.
prepare_restricted_log() {
  local path="$1"
  local owner="${2:-}"
  local mode="${3:-600}"
  local dir base tmp

  dir="$(dirname "$path")"
  base="$(basename "$path")"
  tmp="$(mktemp "${dir}/.${base}.tmp.XXXXXX")" || return 1
  : >"$tmp" || {
    rm -f "$tmp"
    return 1
  }
  if [ "$(id -u)" -eq 0 ] && [ -n "$owner" ] && ! chown "$owner" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  if ! chmod "$mode" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  if ! mv -f "$tmp" "$path"; then
    rm -f "$tmp"
    return 1
  fi
}

_START_LOG="/tmp/nemoclaw-start.log"
if [ "$(id -u)" -eq 0 ]; then
  prepare_restricted_log "$_START_LOG" root:root 600
else
  prepare_restricted_log "$_START_LOG" "" 600
fi
exec > >(tee -a "$_START_LOG") 2> >(tee -a "$_START_LOG" >&2)

# ── Drop unnecessary Linux capabilities (shared) ────────────────
drop_capabilities /usr/local/bin/nemoclaw-start "$@"

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
HERMES_HASH_FILE="${HERMES_IMMUTABLE}/.config-hash"

# verify_config_integrity is provided by sandbox-init.sh; called below.

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

# Atomic temp-file-then-mv rewrite of an rc-file marker block. Refuses
# symlinks. Mirrors upstream NemoClaw's rewrite_rc_marker_block.
rewrite_rc_marker_block() {
  local rc_file="$1"
  local marker_begin="$2"
  local marker_end="$3"
  local snippet="${4:-}"
  local dir base tmp

  [ -e "$rc_file" ] || return 0
  if [ -L "$rc_file" ] || [ ! -f "$rc_file" ]; then
    echo "[SECURITY] refusing unsafe rc file: $rc_file" >&2
    return 1
  fi

  dir="$(dirname "$rc_file")"
  base="$(basename "$rc_file")"
  tmp="$(mktemp "${dir}/.${base}.tmp.XXXXXX")" || return 1

  awk -v b="$marker_begin" -v e="$marker_end" \
    '$0==b{s=1;next} $0==e{s=0;next} !s' "$rc_file" >"$tmp" 2>/dev/null || {
    rm -f "$tmp"
    return 1
  }

  if [ -n "$snippet" ]; then
    printf '%s\n' "$snippet" >>"$tmp" || {
      rm -f "$tmp"
      return 1
    }
  fi

  if [ "$(id -u)" -eq 0 ] && ! chown root:root "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  chmod 644 "$tmp" 2>/dev/null || true

  if [ -L "$rc_file" ]; then
    echo "[SECURITY] refusing symlinked rc file during replace: $rc_file" >&2
    rm -f "$tmp"
    return 1
  fi
  mv -f "$tmp" "$rc_file" 2>/dev/null || {
    rm -f "$tmp"
    return 1
  }
}

rewrite_rc_marker_block_or_fail_in_root() {
  local rc_file="$1"
  if rewrite_rc_marker_block "$@"; then
    return 0
  fi
  if [ "$(id -u)" -eq 0 ]; then
    return 1
  fi
  echo "[setup] could not update rc file ${rc_file}; continuing in non-root mode" >&2
  return 0
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
      echo "NemoClaw manages sandbox config from the host for integrity checks." >&2
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
    [ -f "$rc_file" ] || continue
    rewrite_rc_marker_block_or_fail_in_root "$rc_file" "$marker_begin" "$marker_end" "$snippet"
  done
  # Lock .bashrc/.profile after all mutations are complete (best-effort in non-root).
  lock_rc_files "$_SANDBOX_HOME"
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

# Override the shared configure_messaging_channels with one that also
# reports the outlook bridge channel (specific to this example).
configure_messaging_channels() {
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

start_gateway_log_stream() {
  { tail -n +1 -F /tmp/gateway.log 2>/dev/null | sed -u 's/^/[gateway-log:] /' >&2; } &
  GATEWAY_LOG_TAIL_PID=$!
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

# Outlook bridge / MS Graph sidecar PIDs (populated at launch).
OUTLOOK_BRIDGE_PID=""
MS_GRAPH_SIDECAR_PID=""

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

# cleanup_on_signal is provided by sandbox-init.sh. It reads
# SANDBOX_CHILD_PIDS (array of all PIDs) and SANDBOX_WAIT_PID (the
# primary process whose exit status is returned).
# Each code path below sets these before registering the trap.

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

# Resolve sandbox home dir early — used by install_configure_guard below.
if [ "$(id -u)" -eq 0 ]; then
  _SANDBOX_HOME=$(getent passwd sandbox 2>/dev/null | cut -d: -f6)
  _SANDBOX_HOME="${_SANDBOX_HOME:-/sandbox}"
else
  _SANDBOX_HOME="${HOME:-/sandbox}"
fi

# SECURITY FIX: Write proxy + tool env to a standalone file via
# emit_sandbox_sourced_file() (root:root 444) instead of appending
# inline to .bashrc/.profile. The old approach left .bashrc writable
# by the sandbox user — same vulnerability class as #2181.
# The base image's /sandbox/.bashrc must source this file.
_PROXY_ENV_FILE="/tmp/nemoclaw-proxy-env.sh"
{
  cat <<PROXYEOF
# Proxy configuration (overrides narrow OpenShell defaults on connect)
export HTTP_PROXY="$_PROXY_URL"
export HTTPS_PROXY="$_PROXY_URL"
export NO_PROXY="$_NO_PROXY_VAL"
export http_proxy="$_PROXY_URL"
export https_proxy="$_PROXY_URL"
export no_proxy="$_NO_PROXY_VAL"
export HERMES_HOME="${HERMES_WRITABLE}"
export SLACK_BOT_TOKEN="openshell:resolve:env:SLACK_BOT_TOKEN"
export GITHUB_TOKEN="openshell:resolve:env:GITHUB_TOKEN"
export MS_GRAPH_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"
PROXYEOF
} | emit_sandbox_sourced_file "$_PROXY_ENV_FILE"

# ── Main ─────────────────────────────────────────────────────────

echo 'Setting up NemoClaw (Hermes)...' >&2

# ── Non-root fallback ──────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  echo "[gateway] Running as non-root (uid=$(id -u)) — privilege separation disabled" >&2
  export HOME=/sandbox
  export HERMES_HOME="${HERMES_WRITABLE}"

  if ! verify_config_integrity "${HERMES_IMMUTABLE}" "${HERMES_HASH_FILE}"; then
    echo "[SECURITY] Config integrity check failed — refusing to start (non-root mode)" >&2
    exit 1
  fi
  deploy_config_to_writable
  install_configure_guard
  configure_messaging_channels

  if [ ${#NEMOCLAW_CMD[@]} -gt 0 ]; then
    exec "${NEMOCLAW_CMD[@]}"
  fi

  prepare_restricted_log /tmp/gateway.log "" 600

  # Defence-in-depth: verify /tmp file permissions before launching services.
  # shellcheck disable=SC2119
  validate_tmp_permissions

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
  start_gateway_log_stream

  # NOTE: PIDs are collected after launch; a signal arriving between trap
  # registration and the final append is a small race window (same as before
  # the shared-library refactor). Acceptable for entrypoint-level cleanup.
  SANDBOX_CHILD_PIDS=("$GATEWAY_PID")
  [ -n "${DECODE_PROXY_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$DECODE_PROXY_PID")
  [ -n "${GATEWAY_LOG_TAIL_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$GATEWAY_LOG_TAIL_PID")
  # shellcheck disable=SC2034  # read by cleanup_on_signal from sandbox-init.sh
  SANDBOX_WAIT_PID="$GATEWAY_PID"
  trap cleanup_on_signal SIGTERM SIGINT

  start_socat_forwarder
  [ -n "${SOCAT_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$SOCAT_PID")
  start_ms_graph_sidecar
  [ -n "${MS_GRAPH_SIDECAR_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$MS_GRAPH_SIDECAR_PID")
  start_outlook_bridge
  [ -n "${OUTLOOK_BRIDGE_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$OUTLOOK_BRIDGE_PID")
  print_dashboard_urls

  wait "$GATEWAY_PID"
  exit $?
fi

# ── Root path (full privilege separation via gosu) ─────────────

verify_config_integrity "${HERMES_IMMUTABLE}" "${HERMES_HASH_FILE}"
deploy_config_to_writable
install_configure_guard
configure_messaging_channels

if [ ${#NEMOCLAW_CMD[@]} -gt 0 ]; then
  exec gosu sandbox "${NEMOCLAW_CMD[@]}"
fi

# SECURITY: Protect gateway log from sandbox user tampering.
prepare_restricted_log /tmp/gateway.log gateway:gateway 600

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

# Defence-in-depth: verify /tmp file permissions before launching services.
# shellcheck disable=SC2119
validate_tmp_permissions

# Verify ALL symlinks in .hermes point to expected .hermes-data targets.
validate_config_symlinks "${HERMES_IMMUTABLE}" "${HERMES_WRITABLE}"

# Lock .hermes directory after validation.
harden_config_symlinks "${HERMES_IMMUTABLE}" "hermes"

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
start_gateway_log_stream

# NOTE: PIDs are collected after launch; a signal arriving between trap
# registration and the final append is a small race window (same as before
# the shared-library refactor). Acceptable for entrypoint-level cleanup.
SANDBOX_CHILD_PIDS=("$GATEWAY_PID")
[ -n "${DECODE_PROXY_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$DECODE_PROXY_PID")
[ -n "${GATEWAY_LOG_TAIL_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$GATEWAY_LOG_TAIL_PID")
# shellcheck disable=SC2034  # read by cleanup_on_signal from sandbox-init.sh
SANDBOX_WAIT_PID="$GATEWAY_PID"
trap cleanup_on_signal SIGTERM SIGINT

start_socat_forwarder
[ -n "${SOCAT_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$SOCAT_PID")
start_ms_graph_sidecar
[ -n "${MS_GRAPH_SIDECAR_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$MS_GRAPH_SIDECAR_PID")
start_outlook_bridge
[ -n "${OUTLOOK_BRIDGE_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$OUTLOOK_BRIDGE_PID")
print_dashboard_urls

# Keep container running by waiting on the gateway process.
wait "$GATEWAY_PID"
