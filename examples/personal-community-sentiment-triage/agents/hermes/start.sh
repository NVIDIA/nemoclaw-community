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
NEMO_RELAY_GATEWAY_PORT=4040  # upstream default (crates/cli/src/config.rs)

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

refresh_hermes_provider_placeholders() {
  local env_file="${HERMES_WRITABLE}/.env"
  [ -f "$env_file" ] || return 0

  local keys="TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN GITHUB_TOKEN GH_TOKEN"
  local has_scoped_placeholder=0
  local key value
  for key in $keys; do
    value="${!key:-}"
    case "$value" in
      openshell:resolve:env:*) has_scoped_placeholder=1 ;;
    esac
  done
  [ "$has_scoped_placeholder" -eq 1 ] || return 0

  if [ -L "$env_file" ]; then
    echo "[SECURITY] Refusing Hermes provider placeholder refresh — env path is a symlink" >&2
    return 1
  fi

  NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS="$keys" \
    python3 - "$env_file" <<'PYPLACEHOLDERS'
import os
import sys

env_file = sys.argv[1]
prefix = "openshell:resolve:env:"
keys = os.environ.get("NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS", "").split()
replacements = {}

for key in keys:
    value = os.environ.get(key, "")
    if value.startswith(prefix):
        replacements[key] = value

if not replacements:
    sys.exit(0)

with open(env_file, encoding="utf-8") as f:
    lines = f.readlines()

changed = False
updated = []
seen = set()
for line in lines:
    stripped = line.rstrip("\n")
    replaced = False
    for key, value in replacements.items():
        if stripped.startswith(f"{key}="):
            new_line = f"{key}={value}\n"
            updated.append(new_line)
            seen.add(key)
            changed = changed or new_line != line
            replaced = True
            break
    if not replaced:
        updated.append(line)

for key, value in replacements.items():
    if key not in seen:
        updated.append(f"{key}={value}\n")
        changed = True

if not changed:
    sys.exit(0)

with open(env_file, "w", encoding="utf-8") as f:
    f.writelines(updated)
PYPLACEHOLDERS

  echo "[config] Refreshed Hermes provider placeholders from OpenShell runtime env" >&2
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

# ── Placeholder rewrite proxy ───────────────────────────────────
# Python HTTP clients (httpx) URL-encode colons in paths, breaking
# OpenShell's openshell:resolve:env: placeholder pattern. This proxy
# sits between the Hermes process and the OpenShell proxy, URL-decoding
# request targets so the L7 proxy recognizes REST placeholders. Slack
# SDK-shaped placeholders are canonicalized in the Hermes Python preload
# before HTTPS serialization.
HERMES_VENV_PYTHON="/opt/hermes/.venv/bin/python"
SLACK_SHIMS_DIR="/usr/local/lib/nemoclaw-slack-shims"
PATCHES_DIR="/usr/local/lib/nemoclaw-patches"
DECODE_PROXY_PID=""
DECODE_PROXY_PORT=3129
start_decode_proxy() {
  nohup "$HERMES_VENV_PYTHON" "${SLACK_SHIMS_DIR}/decode-proxy.py" >/dev/null 2>&1 &
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

# ── NeMo-Relay sidecar gateway ──────────────────────────────────
NEMO_RELAY_PID=""
start_nemo_relay_sidecar() {
  if ! [ -x /usr/local/bin/nemo-relay ]; then
    echo "[nemo-relay] binary not found at /usr/local/bin/nemo-relay, skipping" >&2
    return 0
  fi
  if [ "$(id -u)" -eq 0 ]; then
    nohup gosu gateway /usr/local/bin/nemo-relay \
      --bind "127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
      >>/tmp/nemo-relay.log 2>&1 &
  else
    nohup /usr/local/bin/nemo-relay \
      --bind "127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
      >>/tmp/nemo-relay.log 2>&1 &
  fi
  NEMO_RELAY_PID=$!
  # Wait for /healthz so PID-1 hermes doesn't race the sidecar (silent drops).
  local attempts=0
  while [ "$attempts" -lt 30 ]; do
    if curl -sf "http://127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}/healthz" >/dev/null 2>&1; then
      echo "[nemo-relay] sidecar healthy on 127.0.0.1:${NEMO_RELAY_GATEWAY_PORT} (pid $NEMO_RELAY_PID)" >&2
      return 0
    fi
    sleep 0.5
    attempts=$((attempts + 1))
  done
  # Fail-hard: silent telemetry loss is worse than a noisy startup failure.
  # Surface the sidecar's own log so the operator doesn't have to dig.
  echo "[nemo-relay] FATAL: sidecar did not become healthy within 15s (pid $NEMO_RELAY_PID)" >&2
  echo "[nemo-relay] --- last 30 lines of /tmp/nemo-relay.log ---" >&2
  tail -n 30 /tmp/nemo-relay.log >&2 2>/dev/null || echo "[nemo-relay] (log unreadable)" >&2
  echo "[nemo-relay] --- end log ---" >&2
  exit 1
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
  # graph.microsoft.com over HTTPS via the OpenShell proxy.
  # NO_PROXY ensures the local Hermes gateway is always reached directly.
  bridge_env="HERMES_HOME=${HERMES_WRITABLE} \
    MS_GRAPH_SIDECAR_URL=http://127.0.0.1:${SIDECAR_PORT} \
    HTTPS_PROXY=${_PROXY_URL} \
    HTTP_PROXY=${_PROXY_URL} \
    https_proxy=${_PROXY_URL} \
    http_proxy=${_PROXY_URL} \
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
export PYTHONPATH="${PATCHES_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# GitHub credentials reach the sandbox only as OpenShell provider placeholders.
# policy.yaml still limits GitHub egress to repo-scoped REST GET requests.
export GITHUB_READONLY_REPO="${GITHUB_READONLY_REPO:-NVIDIA/OpenShell}"

# OpenShell injects SSL_CERT_FILE/CURL_CA_BUNDLE for its L7 proxy CA. Persist
# them into connect-session shells so Python Slack probes and Hermes tools trust
# the same proxy CA that the entrypoint received at startup.
if [ -n "${SSL_CERT_FILE:-}" ] && [ -f "${SSL_CERT_FILE}" ]; then
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-$SSL_CERT_FILE}"
  export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$SSL_CERT_FILE}"
  export GIT_SSL_CAINFO="${GIT_SSL_CAINFO:-$SSL_CERT_FILE}"
fi
# Preserve provider-injected placeholders from OpenShell 0.37+, which are
# revision-scoped (openshell:resolve:env:v..._KEY). Only fall back to the legacy
# placeholder format when nothing was injected so local/dev flows still boot.
export OUTLOOK_CLIENT_ID="${OUTLOOK_CLIENT_ID:-openshell:resolve:env:OUTLOOK_CLIENT_ID}"
export OUTLOOK_SESSION_UUID="${OUTLOOK_SESSION_UUID:-openshell:resolve:env:OUTLOOK_SESSION_UUID}"
export MS_GRAPH_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"

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
export PYTHONPATH="${PATCHES_DIR}\${PYTHONPATH:+:\${PYTHONPATH}}"
export HERMES_HOME="${HERMES_WRITABLE}"
export SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-openshell:resolve:env:SLACK_BOT_TOKEN}"
export GITHUB_READONLY_REPO="${GITHUB_READONLY_REPO:-NVIDIA/OpenShell}"
export OUTLOOK_CLIENT_ID="${OUTLOOK_CLIENT_ID:-openshell:resolve:env:OUTLOOK_CLIENT_ID}"
export OUTLOOK_SESSION_UUID="${OUTLOOK_SESSION_UUID:-openshell:resolve:env:OUTLOOK_SESSION_UUID}"
export MS_GRAPH_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"
export NEMO_RELAY_GATEWAY_URL="http://127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}"
export PATH="/usr/local/lib/nemoclaw/bin:\$PATH"
export HERMES_TUI_THEME=dark
export HERMES_DISABLE_LAZY_INSTALLS=1
PROXYEOF
  for _ca_env_name in SSL_CERT_FILE CURL_CA_BUNDLE REQUESTS_CA_BUNDLE GIT_SSL_CAINFO; do
    _ca_env_value="${!_ca_env_name:-}"
    if [ -n "$_ca_env_value" ]; then
      printf 'export %s=%q\n' "$_ca_env_name" "$_ca_env_value"
    fi
  done
  for _provider_env_name in GITHUB_TOKEN GH_TOKEN; do
    _provider_env_value="${!_provider_env_name:-}"
    if [ -n "$_provider_env_value" ]; then
      printf 'export %s=%q\n' "$_provider_env_name" "$_provider_env_value"
    fi
  done
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
  refresh_hermes_provider_placeholders
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
  # NeMo-Relay observability is configured via /etc/nemo-relay/plugins.toml
  # (baked at image build time). Verify the binary and config are present.
  if [ -x /usr/local/bin/nemo-relay ] && [ -r /etc/nemo-relay/plugins.toml ]; then
    echo "[nemo-relay] binary + config present (plugins.toml=/etc/nemo-relay/plugins.toml)" | tee -a /tmp/gateway.log >&2
  else
    echo "[nemo-relay] WARNING: binary or config missing — telemetry disabled" | tee -a /tmp/gateway.log >&2
  fi

  # Sidecar must be healthy before PID-1 hermes starts (else first-turn drops).
  start_nemo_relay_sidecar

  HERMES_HOME="${HERMES_WRITABLE}" \
    HTTPS_PROXY="${_PROXY_URL}" \
    HTTP_PROXY="${_PROXY_URL}" \
    https_proxy="${_PROXY_URL}" \
    http_proxy="${_PROXY_URL}" \
    PYTHONPATH="${PATCHES_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    API_SERVER_KEY="nemoclaw-internal" \
    NEMO_RELAY_GATEWAY_URL="http://127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
    nohup hermes gateway run >>/tmp/gateway.log 2>&1 &
  GATEWAY_PID=$!
  echo "[gateway] hermes gateway launched (pid $GATEWAY_PID)" >&2
  start_gateway_log_stream

  # NOTE: PIDs are collected after launch; a signal arriving between trap
  # registration and the final append is a small race window (same as before
  # the shared-library refactor). Acceptable for entrypoint-level cleanup.
  SANDBOX_CHILD_PIDS=("$GATEWAY_PID")
  [ -n "${NEMO_RELAY_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$NEMO_RELAY_PID")
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
refresh_hermes_provider_placeholders
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
# NeMo-Relay observability is configured via /etc/nemo-relay/plugins.toml
# (baked at image build time). Verify the binary and config are present.
if [ -x /usr/local/bin/nemo-relay ] && [ -r /etc/nemo-relay/plugins.toml ]; then
  echo "[nemo-relay] binary + config present (plugins.toml=/etc/nemo-relay/plugins.toml)" | tee -a /tmp/gateway.log >&2
else
  echo "[nemo-relay] WARNING: binary or config missing — telemetry disabled" | tee -a /tmp/gateway.log >&2
fi

# Defence-in-depth: verify /tmp file permissions before launching services.
# shellcheck disable=SC2119
validate_tmp_permissions

# Verify ALL symlinks in .hermes point to expected .hermes-data targets.
validate_config_symlinks "${HERMES_IMMUTABLE}" "${HERMES_WRITABLE}"

# Lock .hermes directory after validation.
harden_config_symlinks "${HERMES_IMMUTABLE}" "hermes"

# Sidecar must be healthy before PID-1 hermes starts (else first-turn drops).
start_nemo_relay_sidecar

# NEMO_RELAY_GATEWAY_URL must be in the explicit launch env — PID-1 hermes
# does not read _PROXY_ENV_FILE, and Slack/Outlook bridge-driven turns funnel
# through this process to emit telemetry.
HERMES_HOME="${HERMES_WRITABLE}" \
  HTTPS_PROXY="${_PROXY_URL}" \
  HTTP_PROXY="${_PROXY_URL}" \
  https_proxy="${_PROXY_URL}" \
  http_proxy="${_PROXY_URL}" \
  PYTHONPATH="${PATCHES_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  API_SERVER_KEY="nemoclaw-internal" \
  NEMO_RELAY_GATEWAY_URL="http://127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
  nohup gosu gateway hermes gateway run \
    >>/tmp/gateway.log 2>&1 &
GATEWAY_PID=$!
echo "[gateway] hermes gateway launched as 'gateway' user (pid $GATEWAY_PID)" >&2
start_gateway_log_stream

# NOTE: PIDs are collected after launch; a signal arriving between trap
# registration and the final append is a small race window (same as before
# the shared-library refactor). Acceptable for entrypoint-level cleanup.
SANDBOX_CHILD_PIDS=("$GATEWAY_PID")
[ -n "${NEMO_RELAY_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$NEMO_RELAY_PID")
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
