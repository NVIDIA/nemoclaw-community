#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$ROOT")"
RUNTIME_DIR="${FINANCE_RUNTIME_DIR:-$ROOT/.runtime}"
ENV_FILE="${FINANCE_ENV_FILE:-}"
NEMOCLAW_REF="${NEMOCLAW_REF:-v0.0.70}"
NEMOCLAW_COMMIT="${NEMOCLAW_COMMIT:-8120223922bf6a501df32a8e269ce9dcf2180819}"
SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-financial-analyst}"
UI_PORT="${FINANCE_UI_PORT:-18080}"
PHOENIX_PORT=6006
NEMOCLAW_SOURCE="$RUNTIME_DIR/nemoclaw-${NEMOCLAW_REF#v}"
NODE_VERSION="v22.23.1"
COMPOSE_FILE="$ROOT/observability/phoenix-compose.yml"

log() {
  printf '[financial-assistant] %s\n' "$*"
}

die() {
  printf '[financial-assistant] ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

ensure_node() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 &&
    node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
    return
  fi

  local machine node_arch checksum archive install_dir
  machine="$(uname -m)"
  case "$machine" in
    x86_64)
      node_arch="x64"
      checksum="9749e988f437343b7fa832c69ded82a312e41a03116d766797ac14f6f9eee578"
      ;;
    aarch64 | arm64)
      node_arch="arm64"
      checksum="0294e8b915ab75f92c7513d2fcb830ae06e10684e6c603e99a87dbf8835389c1"
      ;;
    *) die "unsupported Node.js host architecture: $machine" ;;
  esac

  archive="node-${NODE_VERSION}-linux-${node_arch}.tar.xz"
  install_dir="$RUNTIME_DIR/${archive%.tar.xz}"
  if [[ ! -x "$install_dir/bin/node" || ! -x "$install_dir/bin/npm" ]]; then
    require curl
    require sha256sum
    require tar
    mkdir -p "$RUNTIME_DIR"
    log "installing Node.js ${NODE_VERSION} in .runtime"
    curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/${archive}" \
      -o "$RUNTIME_DIR/$archive"
    printf '%s  %s\n' "$checksum" "$RUNTIME_DIR/$archive" | sha256sum -c -
    tar -xJf "$RUNTIME_DIR/$archive" -C "$RUNTIME_DIR"
    rm -f "$RUNTIME_DIR/$archive"
  fi
  export PATH="$install_dir/bin:$PATH"
  require node
  require npm
}

usage() {
  cat <<'EOF'
Usage: scripts/demo.sh <command>

Commands:
  up       Install/configure the sandbox if needed, then start the demo
  install  Install NemoClaw, onboard Hermes, policies, skills, and SOUL
  start    Start Phoenix, the Hermes forward, and the financial UI
  verify   Run API, skill, native Relay, Phoenix, and UI smoke checks
  status   Print concise service health
  stop     Stop the UI and Phoenix; leave the sandbox intact
  outlook-setup  Configure and attach the optional Outlook provider
  outlook-test   Draft one Outlook reply without sending it
  outlook-start  Start the one-owner Outlook reply poller
  outlook-stop   Stop the Outlook reply poller
EOF
}

resolve_env_file() {
  if [[ -n "$ENV_FILE" ]]; then
    return
  fi
  if [[ -f "$ROOT/.env" ]]; then
    ENV_FILE="$ROOT/.env"
  elif [[ -f "$REPO_ROOT/.env" ]]; then
    ENV_FILE="$REPO_ROOT/.env"
  else
    ENV_FILE="$ROOT/.env"
  fi
}

dotenv_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  python3 - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys

path, key = Path(sys.argv[1]), sys.argv[2]
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() == key:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        print(value)
        break
PY
}

setting() {
  local name fallback value
  name="$1"
  fallback="${2:-}"
  value="${!name:-}"
  if [[ -z "$value" ]]; then
    value="$(dotenv_value "$name")"
  fi
  printf '%s' "${value:-$fallback}"
}

load_runtime_names() {
  resolve_env_file
  SANDBOX_NAME="$(setting NEMOCLAW_SANDBOX_NAME "$SANDBOX_NAME")"
  UI_PORT="$(setting FINANCE_UI_PORT "$UI_PORT")"
  [[ "$UI_PORT" =~ ^[0-9]+$ ]] || die "FINANCE_UI_PORT must be numeric"
}

load_settings() {
  load_runtime_names
  FINANCE_API_URL="$(setting FINANCE_API_URL 'https://integrate.api.nvidia.com/v1')"
  FINANCE_MODEL="$(setting FINANCE_MODEL 'nvidia/nemotron-3-ultra-550b-a55b')"
  FINANCE_API_KEY="$(setting FINANCE_API_KEY)"
  if [[ -z "$FINANCE_API_KEY" ]]; then
    FINANCE_API_KEY="$(setting NVIDIA_INFERENCE_API_KEY)"
  fi
  if [[ -z "$FINANCE_API_KEY" ]]; then
    FINANCE_API_KEY="$(setting NVIDIA_API_KEY)"
  fi
  if [[ -z "$FINANCE_API_KEY" ]]; then
    FINANCE_API_KEY="$(setting COMPATIBLE_API_KEY)"
  fi
  [[ -n "$FINANCE_API_KEY" ]] ||
    die "set FINANCE_API_KEY (or NVIDIA_INFERENCE_API_KEY) in $ENV_FILE"
  [[ -n "$FINANCE_MODEL" ]] || die "set FINANCE_MODEL in $ENV_FILE"
  [[ "$FINANCE_API_URL" == http://* || "$FINANCE_API_URL" == https://* ]] ||
    die "FINANCE_API_URL must be an http(s) URL"
}

load_outlook_settings() {
  load_runtime_names
  OUTLOOK_TARGET_MAILBOX="$(setting OUTLOOK_TARGET_MAILBOX)"
  OUTLOOK_REPLY_TO="$(setting OUTLOOK_REPLY_TO)"
  [[ "$OUTLOOK_TARGET_MAILBOX" == *@* ]] ||
    die "set OUTLOOK_TARGET_MAILBOX in $ENV_FILE"
  [[ "$OUTLOOK_REPLY_TO" == *@* ]] || die "set OUTLOOK_REPLY_TO in $ENV_FILE"
}

prepare_nemoclaw_source() {
  require git
  require python3
  mkdir -p "$RUNTIME_DIR"
  if [[ ! -d "$NEMOCLAW_SOURCE/.git" ]]; then
    log "cloning NemoClaw $NEMOCLAW_REF"
    git clone --depth 1 --branch "$NEMOCLAW_REF" \
      https://github.com/NVIDIA/NemoClaw.git "$NEMOCLAW_SOURCE"
  fi

  local source_commit
  source_commit="$(git -C "$NEMOCLAW_SOURCE" rev-parse --verify HEAD)"
  [[ "$source_commit" == "$NEMOCLAW_COMMIT" ]] ||
    die "$NEMOCLAW_SOURCE is not the expected $NEMOCLAW_REF commit; remove it and retry"
  python3 "$ROOT/scripts/patch_nemoclaw.py" \
    --source "$NEMOCLAW_SOURCE" \
    --relay-config "$ROOT/observability/nemo-relay-plugins.toml"
}

clean_onboard_env() {
  local executable="$1"
  shift
  local provider="custom"
  local clean_path="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  local node_path=""
  if command -v node >/dev/null 2>&1; then
    node_path="$(dirname "$(command -v node)")"
    clean_path="$HOME/.local/bin:$node_path:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  fi
  local -a provider_env=(
    "COMPATIBLE_API_KEY=$FINANCE_API_KEY"
    "NEMOCLAW_ENDPOINT_URL=$FINANCE_API_URL"
  )
  if [[ "$FINANCE_API_URL" == "https://integrate.api.nvidia.com/v1" ]]; then
    provider="build"
    provider_env=("NVIDIA_INFERENCE_API_KEY=$FINANCE_API_KEY")
  fi

  env -i \
    "HOME=$HOME" \
    "USER=${USER:-$(id -un)}" \
    "LOGNAME=${LOGNAME:-$(id -un)}" \
    "PATH=$clean_path" \
    "SHELL=${SHELL:-/bin/bash}" \
    "TERM=${TERM:-xterm-256color}" \
    "LANG=${LANG:-C.UTF-8}" \
    "NEMOCLAW_AGENT=hermes" \
    "NEMOCLAW_NON_INTERACTIVE=1" \
    "NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1" \
    "NEMOCLAW_NO_EXPRESS=1" \
    "NEMOCLAW_SANDBOX_NAME=$SANDBOX_NAME" \
    "NEMOCLAW_PROVIDER=$provider" \
    "NEMOCLAW_MODEL=$FINANCE_MODEL" \
    "NEMOCLAW_PREFERRED_API=completions" \
    "NEMOCLAW_POLICY_MODE=skip" \
    "${provider_env[@]}" \
    "$executable" "$@"
}

sandbox_ready() {
  command -v nemohermes >/dev/null 2>&1 &&
    nemohermes "$SANDBOX_NAME" status >/dev/null 2>&1
}

sandbox_exists() {
  command -v openshell >/dev/null 2>&1 &&
    openshell sandbox get "$SANDBOX_NAME" >/dev/null 2>&1
}

install_nemoclaw() {
  prepare_nemoclaw_source
  export PATH="$HOME/.local/bin:$PATH"

  if sandbox_ready; then
    if [[ "$(nemohermes --version 2>/dev/null)" != "nemohermes ${NEMOCLAW_REF}" ]]; then
      die "healthy sandbox uses $(nemohermes --version), expected NemoClaw $NEMOCLAW_REF"
    fi
    log "reusing healthy Hermes sandbox $SANDBOX_NAME"
  elif sandbox_exists; then
    die "sandbox $SANDBOX_NAME exists but is unhealthy; inspect logs, then destroy it before reinstalling"
  else
    log "installing pinned NemoClaw and onboarding Hermes from source"
    clean_onboard_env bash "$NEMOCLAW_SOURCE/scripts/install.sh" \
      --non-interactive --yes-i-accept-third-party-software --fresh
    hash -r
    export PATH="$HOME/.local/bin:$PATH"
  fi

  sandbox_ready || die "Hermes sandbox $SANDBOX_NAME is not healthy after onboarding"
}

start_phoenix() {
  require curl
  require docker
  log "starting Phoenix"
  docker compose -f "$COMPOSE_FILE" up -d --quiet-pull
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$PHOENIX_PORT/" >/dev/null 2>&1 && return 0
    sleep 2
  done
  docker compose -f "$COMPOSE_FILE" logs --tail 80 >&2 || true
  die "Phoenix did not become healthy"
}

configuration_fingerprint() {
  python3 - "$ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

root = Path(sys.argv[1])
paths = [
    root / "agents/hermes/SOUL.md",
    root / "presets/finance-data-readonly.yaml",
    root / "presets/financial-phoenix-relay.yaml",
]
paths.extend(path for path in (root / "skills").rglob("*") if path.is_file())

digest = sha256()
for path in sorted(paths):
    digest.update(path.relative_to(root).as_posix().encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

configure_sandbox() {
  local fingerprint marker
  fingerprint="$(configuration_fingerprint)"
  marker="/sandbox/.financial-assistant-configuration.sha256"
  if nemohermes "$SANDBOX_NAME" exec -- \
    /bin/grep -qx "$fingerprint" "$marker" >/dev/null 2>&1; then
    log "finance policy, skills, and SOUL are already current"
    return
  fi

  log "applying read-only finance and Phoenix policies"
  nemohermes "$SANDBOX_NAME" policy-add \
    --from-file "$ROOT/presets/finance-data-readonly.yaml" --yes
  nemohermes "$SANDBOX_NAME" policy-add \
    --from-file "$ROOT/presets/financial-phoenix-relay.yaml" --yes

  log "installing finance skills"
  local skill
  for skill in "$ROOT"/skills/*; do
    [[ -d "$skill" ]] || continue
    nemohermes "$SANDBOX_NAME" skill install "$skill"
  done

  log "installing the financial assistant SOUL"
  nemohermes "$SANDBOX_NAME" upload \
    "$ROOT/agents/hermes/SOUL.md" /sandbox/.hermes/SOUL.md

  nemohermes "$SANDBOX_NAME" exec -- /opt/hermes/.venv/bin/python -c \
    'import plugins.observability.nemo_relay'
  nemohermes "$SANDBOX_NAME" exec -- /bin/sh -lc \
    'grep -q "observability/nemo_relay" /sandbox/.hermes/config.yaml && test -r /etc/nemo-relay/plugins.toml'

  local marker_source="$RUNTIME_DIR/financial-assistant-configuration.sha256"
  printf '%s\n' "$fingerprint" >"$marker_source"
  nemohermes "$SANDBOX_NAME" upload "$marker_source" "$marker"
  rm -f "$marker_source"
}

forward_is_owned() {
  local forward_list
  forward_list="$(openshell forward list 2>/dev/null || true)"
  FORWARD_LIST_TEXT="$forward_list" python3 - "$SANDBOX_NAME" <<'PY'
import os
import re
import sys

ansi = re.compile(r"\x1B(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\)|[@-_])")
sandbox = sys.argv[1]
columns = None
for raw_line in os.environ.get("FORWARD_LIST_TEXT", "").splitlines():
    parts = ansi.sub("", raw_line).split()
    upper = [part.upper() for part in parts]
    if {"SANDBOX", "PORT", "STATUS"}.issubset(upper):
        columns = {name: upper.index(name) for name in ("SANDBOX", "PORT", "STATUS")}
        continue
    if (
        columns is not None
        and len(parts) > max(columns.values())
        and parts[columns["SANDBOX"]] == sandbox
        and parts[columns["PORT"]] == "8642"
        and parts[columns["STATUS"]].lower() in {"running", "active"}
    ):
        raise SystemExit(0)
raise SystemExit(1)
PY
}

ensure_hermes_forward() {
  if curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1; then
    forward_is_owned && return
    die "port 8642 is healthy but is not owned by the $SANDBOX_NAME OpenShell forward"
  fi
  if forward_is_owned; then
    openshell forward stop 8642 "$SANDBOX_NAME" >/dev/null 2>&1 || true
  fi
  log "starting Hermes API forward on port 8642"
  openshell forward start --background 8642 "$SANDBOX_NAME"
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1 && forward_is_owned; then
      return
    fi
    sleep 1
  done
  die "Hermes API forward did not become healthy on port 8642"
}

stop_pid_file() {
  local pid_file="$1" expected="$2" pid=""
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    if ps -p "$pid" -o command= | grep -Fq "$expected"; then
      kill "$pid"
      for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$pid" 2>/dev/null &&
        ps -p "$pid" -o command= | grep -Fq "$expected"; then
        kill -KILL "$pid"
      fi
    fi
  fi
  rm -f "$pid_file"
}

start_ui() {
  require python3
  ensure_node
  mkdir -p "$RUNTIME_DIR"
  local lock_hash lock_stamp
  lock_hash="$(sha256sum "$ROOT/package-lock.json" | awk '{print $1}')"
  lock_stamp="$ROOT/node_modules/.finance-package-lock.sha256"
  if [[ ! -f "$lock_stamp" || "$(cat "$lock_stamp")" != "$lock_hash" ]]; then
    log "installing UI dependencies"
    npm --prefix "$ROOT" ci
    log "installing the Playwright Chromium browser"
    "$ROOT/node_modules/.bin/playwright" install --with-deps chromium
    printf '%s\n' "$lock_hash" >"$lock_stamp"
  fi
  log "building financial assistant UI"
  npm --prefix "$ROOT" run build

  local token
  token="$(nemohermes "$SANDBOX_NAME" gateway-token --quiet)"
  [[ -n "$token" ]] || die "could not retrieve the Hermes API bearer token"
  stop_pid_file "$RUNTIME_DIR/ui.pid" "finance_ui_server.py"

  log "starting financial assistant UI on port $UI_PORT"
  FINANCE_HERMES_TOKEN="$token" FINANCE_MODEL="$FINANCE_MODEL" \
    nohup python3 "$ROOT/scripts/finance_ui_server.py" \
      --host 0.0.0.0 --port "$UI_PORT" \
      >"$RUNTIME_DIR/ui.log" 2>&1 </dev/null &
  echo $! >"$RUNTIME_DIR/ui.pid"

  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:$UI_PORT/health" >/dev/null 2>&1 && return
    sleep 1
  done
  tail -n 80 "$RUNTIME_DIR/ui.log" >&2 || true
  die "financial assistant UI did not become healthy on port $UI_PORT"
}

install_demo() {
  load_settings
  start_phoenix
  install_nemoclaw
  configure_sandbox
}

start_demo() {
  load_settings
  export PATH="$HOME/.local/bin:$PATH"
  sandbox_ready || die "run scripts/demo.sh install first"
  start_phoenix
  ensure_hermes_forward
  start_ui
  log "UI: http://127.0.0.1:$UI_PORT"
  log "Phoenix: http://127.0.0.1:$PHOENIX_PORT"
}

run_api_smoke() {
  local attempt
  for attempt in 1 2 3; do
    if python3 "$ROOT/scripts/smoke-hermes-api.py" \
      --api-url "http://127.0.0.1:$UI_PORT/v1" \
      --model "$FINANCE_MODEL" --timeout 240; then
      return 0
    fi
    [[ "$attempt" == 3 ]] || {
      log "Hermes API smoke attempt $attempt failed; retrying in 10 seconds"
      sleep 10
    }
  done
  return 1
}

verify_demo() {
  load_settings
  export PATH="$HOME/.local/bin:$PATH"
  ensure_node
  python3 -m unittest discover -s "$ROOT/scripts" -p 'test_*.py'
  run_api_smoke
  FINANCE_UI_URL="http://127.0.0.1:$UI_PORT/" \
    FINANCE_REQUIRE_TRACE_EVENTS=1 \
    npm --prefix "$ROOT" run ui:smoke
}

status_demo() {
  load_runtime_names
  export PATH="$HOME/.local/bin:$PATH"
  sandbox_ready && echo "Hermes:  healthy" || echo "Hermes:  unavailable"
  curl -fsS "http://127.0.0.1:$UI_PORT/health" >/dev/null 2>&1 &&
    echo "UI:      healthy ($UI_PORT)" || echo "UI:      unavailable ($UI_PORT)"
  curl -fsS "http://127.0.0.1:$PHOENIX_PORT/" >/dev/null 2>&1 &&
    echo "Phoenix: healthy ($PHOENIX_PORT)" || echo "Phoenix: unavailable ($PHOENIX_PORT)"
}

stop_demo() {
  stop_pid_file "$RUNTIME_DIR/ui.pid" "finance_ui_server.py"
  docker compose -f "$COMPOSE_FILE" down
  log "stopped UI and Phoenix; sandbox $SANDBOX_NAME remains available"
}

outlook_setup() {
  export PATH="$HOME/.local/bin:$PATH"
  load_runtime_names
  sandbox_ready || die "run scripts/demo.sh up first"
  "$ROOT/scripts/setup-outlook-provider.sh" "$SANDBOX_NAME"
}

outlook_test() {
  export PATH="$HOME/.local/bin:$PATH"
  load_outlook_settings
  sandbox_ready || die "run scripts/demo.sh up first"
  nemohermes "$SANDBOX_NAME" exec -- env \
    "OUTLOOK_TARGET_MAILBOX=$OUTLOOK_TARGET_MAILBOX" \
    "OUTLOOK_REPLY_TO=$OUTLOOK_REPLY_TO" \
    /usr/bin/python3 /sandbox/outlook_finance_bridge.py \
    --limit 1 --reply-mode print
}

outlook_start() {
  export PATH="$HOME/.local/bin:$PATH"
  load_outlook_settings
  sandbox_ready || die "run scripts/demo.sh up first"
  stop_pid_file "$RUNTIME_DIR/outlook.pid" "outlook_finance_bridge.py"
  log "starting the one-owner Outlook reply poller"
  nohup nemohermes "$SANDBOX_NAME" exec -- env \
    "OUTLOOK_TARGET_MAILBOX=$OUTLOOK_TARGET_MAILBOX" \
    "OUTLOOK_REPLY_TO=$OUTLOOK_REPLY_TO" \
    /usr/bin/python3 /sandbox/outlook_finance_bridge.py \
    --poll --interval 30 --limit 2 --reply-mode graph \
    >"$RUNTIME_DIR/outlook.log" 2>&1 </dev/null &
  echo $! >"$RUNTIME_DIR/outlook.pid"
  log "Outlook poller log: $RUNTIME_DIR/outlook.log"
}

outlook_stop() {
  stop_pid_file "$RUNTIME_DIR/outlook.pid" "outlook_finance_bridge.py"
  log "stopped the Outlook reply poller"
}

main() {
  local command="${1:-}"
  case "$command" in
    up)
      install_demo
      start_demo
      verify_demo
      ;;
    install) install_demo ;;
    start) start_demo ;;
    verify) verify_demo ;;
    status) status_demo ;;
    stop) stop_demo ;;
    outlook-setup) outlook_setup ;;
    outlook-test) outlook_test ;;
    outlook-start) outlook_start ;;
    outlook-stop) outlook_stop ;;
    -h | --help | help) usage ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
