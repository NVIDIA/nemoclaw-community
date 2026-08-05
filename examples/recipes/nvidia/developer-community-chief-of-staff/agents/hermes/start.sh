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

# ── ATIF storage probe (computed once) ───────────────────────────
# "Enabled" iff plugins.toml has the [[components.config.atif.storage]]
# block. Set at image-build time (Dockerfile emits it when ATIF_EXPORT_MODE
# is relay), so the runtime check here is authoritative
# regardless of what env vars OpenShell's exec-session allowlist did or
# didn't propagate. Drives the atif-bridge gate and the AWS_* exports
# below; all three are in lockstep — either all on or all off.
ATIF_STORAGE_ENABLED=0
if grep -q '^\[\[components\.config\.atif\.storage\]\]' /etc/nemo-relay/plugins.toml 2>/dev/null; then
  ATIF_STORAGE_ENABLED=1
fi

# ── Early stderr/stdout capture ──────────────────────────────────
# Capture all entrypoint output to /tmp/nemoclaw-start.log so startup
# failures before /tmp/gateway.log exists are still diagnosable.
prepare_restricted_log() {
  local path="$1"
  local mode="${2:-600}"
  local dir base tmp

  dir="$(dirname "$path")"
  base="$(basename "$path")"
  tmp="$(mktemp "${dir}/.${base}.tmp.XXXXXX")" || return 1
  : >"$tmp" || {
    rm -f "$tmp"
    return 1
  }
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
prepare_restricted_log "$_START_LOG" 600
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
  cp "${HERMES_IMMUTABLE}/config.yaml" "${HERMES_WRITABLE}/config.yaml"
  cp "${HERMES_IMMUTABLE}/.env" "${HERMES_WRITABLE}/.env"
  chmod 600 "${HERMES_WRITABLE}/config.yaml" "${HERMES_WRITABLE}/.env" 2>/dev/null || true
  echo "[config] Deployed verified config to ${HERMES_WRITABLE}" >&2
}

refresh_hermes_provider_placeholders() {
  local env_file="${HERMES_WRITABLE}/.env"
  [ -f "$env_file" ] || return 0

  local keys="TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN GITHUB_TOKEN"
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
    python3 /usr/local/lib/nemoclaw/refresh-placeholders.py "$env_file"

  echo "[config] Refreshed Hermes provider placeholders from OpenShell runtime env" >&2
}

_has_outlook_channel() {
  # MS_GRAPH_ACCESS_TOKEN is injected by the OpenShell v2 outlook provider when
  # attached; its presence signals the Outlook channel is wired up.
  [ -n "${MS_GRAPH_ACCESS_TOKEN:-}" ] \
    || echo "${NEMOCLAW_MESSAGING_CHANNELS_B64:-W10=}" \
    | python3 -c "import sys,base64,json; d=json.loads(base64.b64decode(sys.stdin.read().strip())); sys.exit(0 if 'outlook' in d else 1)" 2>/dev/null
}

# Override the shared configure_messaging_channels with one that also
# reports the outlook bridge channel (specific to this example).
configure_messaging_channels() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -n "${DISCORD_BOT_TOKEN:-}" ] \
    || [ -n "${SLACK_BOT_TOKEN:-}" ] || _has_outlook_channel || return 0

  echo "[channels] Messaging channels active (channel set baked; per-user auth via runtime env):" >&2
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

# PATCHES_DIR is referenced by PYTHONPATH below + the _PROXY_ENV_FILE export.
PATCHES_DIR="/usr/local/lib/nemoclaw-patches"

# ── NeMo-Relay sidecar gateway ──────────────────────────────────
NEMO_RELAY_PID=""
start_nemo_relay_sidecar() {
  if ! [ -x /usr/local/bin/nemo-relay ]; then
    echo "[nemo-relay] binary not found at /usr/local/bin/nemo-relay, skipping" >&2
    return 0
  fi
  nohup /usr/local/bin/nemo-relay \
    --bind "127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
    >>/tmp/nemo-relay.log 2>&1 &
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

# ── ATIF protocol-bridge sidecar ──────────────────────────────────
# Tiny HTTP→HTTPS shim that lets nemo-relay-cli (rustls via object_store /
# reqwest) reach the host atif-export-relay over TLS. rustls 0.23+ rejects
# OpenShell's L7-proxy MITM cert because the cert lacks the serverAuth EKU
# extension (OpenShell `crates/openshell-sandbox/src/l7/tls.rs:115-135`).
# The bridge re-emits each request as HTTPS via Python's ssl module
# (OpenSSL backend), which accepts certs without that EKU — same property
# that lets curl / Python requests / git / every other Hermes outbound work
# through the same L7 proxy today. nemo-relay points at the bridge over
# loopback HTTP; the bridge talks HTTPS upstream; the L7 proxy MITMs and
# substitutes the AWS_SESSION_TOKEN placeholder during that hop. Bearer
# stays in L7 proxy process memory only.
ATIF_BRIDGE_PID=""
start_atif_bridge() {
  # Only start when ATIF S3 export is configured — see ATIF_STORAGE_ENABLED
  # probe at top of script.
  [ "$ATIF_STORAGE_ENABLED" = "1" ] || return 0
  # Readability suffices — we invoke as `python3 <path>`, so the file
  # doesn't need the executable bit (and Dockerfile's `chmod -R a+rX`
  # deliberately doesn't set +x on regular files).
  if ! [ -r /usr/local/lib/nemoclaw-bridges/atif/atif-bridge.py ]; then
    echo "[atif-bridge] /usr/local/lib/nemoclaw-bridges/atif/atif-bridge.py not readable, skipping" >&2
    return 0
  fi
  # Scrub credential-shaped env vars before handing off to the bridge.
  # Defense in depth: bridge.py also refuses to start if any of these are
  # set. Belt-and-suspenders so a future start.sh regression can't silently
  # leak a bearer into the bridge's process memory.
  local scrub=(
    -u ATIF_RELAY_AUTH_TOKEN
    -u AWS_SESSION_TOKEN
    -u AWS_ACCESS_KEY_ID
    -u AWS_SECRET_ACCESS_KEY
    -u GITHUB_TOKEN
    -u MS_GRAPH_ACCESS_TOKEN
    -u SLACK_BOT_TOKEN
  )
  nohup env "${scrub[@]}" \
    ATIF_BRIDGE_UPSTREAM_URL="${ATIF_RELAY_ENDPOINT:-https://host.openshell.internal:18443}" \
    python3 /usr/local/lib/nemoclaw-bridges/atif/atif-bridge.py \
    >>/tmp/atif-bridge.log 2>&1 &
  ATIF_BRIDGE_PID=$!
  local attempts=0
  while [ "$attempts" -lt 30 ]; do
    if curl -sf "http://127.0.0.1:18444/healthz" >/dev/null 2>&1; then
      echo "[atif-bridge] healthy on 127.0.0.1:18444 (pid $ATIF_BRIDGE_PID)" >&2
      return 0
    fi
    sleep 0.5
    attempts=$((attempts + 1))
  done
  # Fail-hard: if the bridge isn't up, every trace upload would return
  # ECONNREFUSED. Quieter than a silent telemetry loss.
  echo "[atif-bridge] FATAL: bridge did not become healthy within 15s (pid $ATIF_BRIDGE_PID)" >&2
  echo "[atif-bridge] --- last 30 lines of /tmp/atif-bridge.log ---" >&2
  tail -n 30 /tmp/atif-bridge.log >&2 2>/dev/null || echo "[atif-bridge] (log unreadable)" >&2
  echo "[atif-bridge] --- end log ---" >&2
  exit 1
}

# Outlook bridge PID (populated at launch).
OUTLOOK_BRIDGE_PID=""

start_outlook_bridge() {
  if ! _has_outlook_channel; then
    return 0
  fi
  [ -f /usr/local/lib/nemoclaw-bridges/outlook/outlook-bridge.py ] || {
    echo "[outlook-bridge] bridge script not found, skipping" >&2
    return 0
  }
  # The bridge dials graph.microsoft.com directly with
  # Authorization: Bearer openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN — the
  # OpenShell L7 proxy substitutes a gateway-refreshed access token on egress.
  local bridge_env
  bridge_env="HERMES_HOME=${HERMES_WRITABLE} \
    HTTPS_PROXY=${_PROXY_URL} \
    HTTP_PROXY=${_PROXY_URL} \
    https_proxy=${_PROXY_URL} \
    http_proxy=${_PROXY_URL} \
    NO_PROXY=localhost,127.0.0.1,::1 \
    no_proxy=localhost,127.0.0.1,::1"
  # shellcheck disable=SC2086
  nohup env ${bridge_env} python3 /usr/local/lib/nemoclaw-bridges/outlook/outlook-bridge.py \
    >>/tmp/outlook-bridge.log 2>&1 &
  OUTLOOK_BRIDGE_PID=$!
  echo "[outlook-bridge] started (pid ${OUTLOOK_BRIDGE_PID})" >&2
}

# ── Launch helpers ──────────────────────────────────────────────

# Prepare /tmp/gateway.log + /tmp/atif, verify NeMo-Relay binary+config, and
# start the sidecar.
prepare_runtime() {
  prepare_restricted_log /tmp/gateway.log 600
  # shellcheck disable=SC2119
  validate_tmp_permissions
  mkdir -p /tmp/atif
  if [ -x /usr/local/bin/nemo-relay ] && [ -r /etc/nemo-relay/plugins.toml ]; then
    echo "[nemo-relay] binary + config present (plugins.toml=/etc/nemo-relay/plugins.toml)" | tee -a /tmp/gateway.log >&2
  else
    echo "[nemo-relay] WARNING: binary or config missing — telemetry disabled" | tee -a /tmp/gateway.log >&2
  fi
  # Bridge must be up before nemo-relay so the first PutObject doesn't race
  # against a closed bridge port.
  start_atif_bridge
  start_nemo_relay_sidecar
}

# Launch the Hermes gateway with the standard env block.
launch_hermes_gateway() {
  HERMES_HOME="${HERMES_WRITABLE}" \
    HTTPS_PROXY="${_PROXY_URL}" HTTP_PROXY="${_PROXY_URL}" \
    https_proxy="${_PROXY_URL}" http_proxy="${_PROXY_URL}" \
    PYTHONPATH="${PATCHES_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    API_SERVER_KEY="nemoclaw-internal" \
    NEMO_RELAY_GATEWAY_URL="http://127.0.0.1:${NEMO_RELAY_GATEWAY_PORT}" \
    nohup hermes gateway run >>/tmp/gateway.log 2>&1 &
  GATEWAY_PID=$!
  echo "[gateway] hermes gateway launched (pid $GATEWAY_PID)" >&2
}

# Wire up supervisor PIDs, signal trap, and side-services after the gateway
# is launched. Reads GATEWAY_PID; populates SANDBOX_CHILD_PIDS + SANDBOX_WAIT_PID.
wire_post_launch_supervision() {
  start_gateway_log_stream

  SANDBOX_CHILD_PIDS=("$GATEWAY_PID")
  [ -n "${NEMO_RELAY_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$NEMO_RELAY_PID")
  [ -n "${ATIF_BRIDGE_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$ATIF_BRIDGE_PID")
  [ -n "${GATEWAY_LOG_TAIL_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$GATEWAY_LOG_TAIL_PID")
  # shellcheck disable=SC2034  # read by cleanup_on_signal from sandbox-init.sh
  SANDBOX_WAIT_PID="$GATEWAY_PID"
  trap cleanup_on_signal SIGTERM SIGINT

  start_socat_forwarder
  [ -n "${SOCAT_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$SOCAT_PID")
  start_outlook_bridge
  [ -n "${OUTLOOK_BRIDGE_PID:-}" ] && SANDBOX_CHILD_PIDS+=("$OUTLOOK_BRIDGE_PID")
  print_dashboard_urls
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
# Preserve provider-injected MS_GRAPH_ACCESS_TOKEN placeholder for outbound Graph
# calls. Fall back to the literal placeholder string so local/dev flows still boot
# (the L7 proxy substitutes it when the v2 outlook provider is attached).
export MS_GRAPH_ACCESS_TOKEN="${MS_GRAPH_ACCESS_TOKEN:-openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN}"

# ATIF S3 export — Nemo Relay's `object_store` reads AWS_* env vars at
# startup. The per-sandbox bearer rides in AWS_SESSION_TOKEN: the SDK
# emits that env var verbatim as a standalone `x-amz-security-token`
# HTTP header, which matches OpenShell's L7-proxy whole-header-value
# substitution path. AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are
# intentionally literal junk — the SDK builds a SigV4 Authorization
# envelope with them, but it's purely vestigial (atif-export-relay
# never verifies SigV4; it reads the bearer from x-amz-security-token).
#
# AWS_ENDPOINT_URL points at the in-container atif-bridge sidecar on
# loopback (start_atif_bridge above). The bridge re-emits each request
# as HTTPS to host.openshell.internal:18443 using Python's ssl module
# (OpenSSL backend), which the L7 proxy MITMs and substitutes during
# transit. The real bearer never enters nemo-relay or bridge memory;
# only the L7 proxy resolves the placeholder. See docs/atif-export.md
# "Sandbox→relay TLS via Python protocol-bridge sidecar" for the wire
# diagram and the OpenShell EKU bug that makes the bridge necessary.
# Production downstream (relay → real S3 / MinIO) is end-to-end HTTPS
# via boto3. Gated on ATIF_STORAGE_ENABLED so local-mode sandboxes don't
# carry six dead AWS_* vars that imply S3 export is happening when it
# isn't.
if [ "$ATIF_STORAGE_ENABLED" = "1" ]; then
  export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-nemo-relay-sandbox}"
  export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-relay-ignores-this-value}"
  export AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN}"
  export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://127.0.0.1:18444}"
  export AWS_ALLOW_HTTP="${AWS_ALLOW_HTTP:-true}"
  # Vestigial signing region — the SigV4 envelope is junk the relay ignores and
  # re-signs with its own (relay-owned) region. Fixed placeholder, not configurable.
  export AWS_REGION="${AWS_REGION:-us-east-1}"
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
export PYTHONPATH="${PATCHES_DIR}\${PYTHONPATH:+:\${PYTHONPATH}}"
export HERMES_HOME="${HERMES_WRITABLE}"
export SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-openshell:resolve:env:SLACK_BOT_TOKEN}"
export GITHUB_READONLY_REPO="${GITHUB_READONLY_REPO:-NVIDIA/OpenShell}"
export MS_GRAPH_ACCESS_TOKEN="${MS_GRAPH_ACCESS_TOKEN:-openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN}"
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
  for _provider_env_name in GITHUB_TOKEN; do
    _provider_env_value="${!_provider_env_name:-}"
    if [ -n "$_provider_env_value" ]; then
      printf 'export %s=%q\n' "$_provider_env_name" "$_provider_env_value"
    fi
  done
  # Per-user config injected via `-- env` at sandbox-create (kept out of the image
  # so it stays generic). PID-1 (gateway + bridges) inherit these directly; re-emit
  # them here so interactive `hermes` shells (exec/SSH) see the same Outlook mailbox
  # and Slack authorization — otherwise a manually-run gateway has no allowlist and
  # denies every Slack user. Emit only what's set; SLACK_ALLOWED_USERS and
  # SLACK_ALLOW_ALL_USERS are mutually exclusive (see scripts/03-sandbox.sh).
  for _runtime_env_name in \
    OUTLOOK_TARGET_MAILBOX OUTLOOK_REPLY_TO OUTLOOK_ALLOWED_SENDERS \
    SLACK_ALLOWED_USERS SLACK_ALLOW_ALL_USERS; do
    _runtime_env_value="${!_runtime_env_name:-}"
    if [ -n "$_runtime_env_value" ]; then
      printf 'export %s=%q\n' "$_runtime_env_name" "$_runtime_env_value"
    fi
  done
  # AWS_* for ATIF S3 export, re-emitted to the proxy env file so sandbox-user
  # shells inherit them (mechanism explained on the first AWS_* export block
  # above). Gated on ATIF_STORAGE_ENABLED so local-mode shells see no dead exports.
  if [ "$ATIF_STORAGE_ENABLED" = "1" ]; then
    cat <<'STORAGEEOF'
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-nemo-relay-sandbox}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-relay-ignores-this-value}"
export AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN}"
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://127.0.0.1:18444}"
export AWS_ALLOW_HTTP="${AWS_ALLOW_HTTP:-true}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
STORAGEEOF
  fi
} | emit_sandbox_sourced_file "$_PROXY_ENV_FILE"

# ── Main ─────────────────────────────────────────────────────────

echo "Setting up NemoClaw (Hermes) as $(id -un) (uid=$(id -u))..." >&2

export HOME=/sandbox
export HERMES_HOME="${HERMES_WRITABLE}"

if ! verify_config_integrity "${HERMES_IMMUTABLE}" "${HERMES_HASH_FILE}"; then
  echo "[SECURITY] Config integrity check failed — refusing to start" >&2
  exit 1
fi
deploy_config_to_writable
refresh_hermes_provider_placeholders
configure_messaging_channels

if [ ${#NEMOCLAW_CMD[@]} -gt 0 ]; then
  exec "${NEMOCLAW_CMD[@]}"
fi

prepare_runtime
launch_hermes_gateway
wire_post_launch_supervision

# Keep container running by waiting on the gateway process.
wait "$GATEWAY_PID"
