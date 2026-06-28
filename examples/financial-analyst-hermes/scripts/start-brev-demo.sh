#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Start the financial assistant demo runtime on a Brev instance.
#
# This starts the known-good booth path:
#   browser -> finance_ui_server :18080 -> Hermes :8642 -> NeMo Relay :4040
#                                      \-> Phoenix GraphQL :6006

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-.env}"
UI_PORT="${FINANCE_UI_PORT:-18080}"
RELAY_PORT="${FINANCE_RELAY_PORT:-4040}"
PHOENIX_PORT="${FINANCE_PHOENIX_PORT:-6006}"
HERMES_API_URL="${FINANCE_HERMES_API_URL:-http://127.0.0.1:8642}"
LOG_DIR="${FINANCE_RUNTIME_LOG_DIR:-$ROOT/.runtime}"
SKIP_BUILD="${FINANCE_SKIP_BUILD:-0}"
SKIP_PHOENIX="${FINANCE_SKIP_PHOENIX:-0}"

mkdir -p "$LOG_DIR"

log() {
  printf '[finance-demo] %s\n' "$*"
}

die() {
  printf '[finance-demo] ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    die "missing $ENV_FILE; copy .env.example to .env and set FINANCE_API_KEY, FINANCE_API_URL, and FINANCE_MODEL"
  fi

  set -a
  set +u
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set -u
  set +a

  : "${FINANCE_API_URL:?set FINANCE_API_URL in $ENV_FILE, including /v1}"
  : "${FINANCE_API_KEY:?set FINANCE_API_KEY in $ENV_FILE}"
  : "${FINANCE_MODEL:?set FINANCE_MODEL in $ENV_FILE}"

  export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$FINANCE_API_KEY}"
  export PHOENIX_PROJECT_NAME="${PHOENIX_PROJECT_NAME:-financial-assistant-relay}"
}

start_phoenix() {
  if [[ "$SKIP_PHOENIX" == "1" ]]; then
    log "skipping Phoenix because FINANCE_SKIP_PHOENIX=1"
    return
  fi

  require docker
  log "starting Phoenix on 127.0.0.1:$PHOENIX_PORT"
  docker compose -f observability/phoenix-compose.yml up -d

  for _ in {1..30}; do
    if curl -fsS "http://127.0.0.1:$PHOENIX_PORT/" >/dev/null 2>&1; then
      log "Phoenix is reachable"
      return
    fi
    sleep 1
  done

  die "Phoenix did not become reachable on 127.0.0.1:$PHOENIX_PORT"
}

relay_bin() {
  if command -v nemo-relay >/dev/null 2>&1; then
    command -v nemo-relay
    return
  fi
  if [[ -x /home/ubuntu/.local/bin/nemo-relay ]]; then
    printf '%s\n' /home/ubuntu/.local/bin/nemo-relay
    return
  fi
  die "nemo-relay was not found. Install NeMo Relay or add it to PATH before running this script."
}

write_relay_config() {
  mkdir -p .nemo-relay
  cat > .nemo-relay/plugins.toml <<EOF
version = 1

[[components]]
kind = "observability"
enabled = true

[components.config.atif]
enabled = true
output_directory = "/tmp/finance-assistant-atif"

[components.config.openinference]
enabled = true
transport = "http_binary"
endpoint = "http://127.0.0.1:${PHOENIX_PORT}/v1/traces"
service_name = "financial-assistant-agent"
timeout_millis = 3000

[components.config.openinference.resource_attributes]
"openinference.project.name" = "${PHOENIX_PROJECT_NAME}"
"deployment.environment" = "brev-demo"
"demo.channel" = "web-outlook"
EOF
}

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      sleep 1
    fi
  fi
}

start_relay() {
  local bin
  bin="$(relay_bin)"

  write_relay_config
  stop_pid_file "$LOG_DIR/nemo-relay.pid"

  log "starting NeMo Relay on 0.0.0.0:$RELAY_PORT"
  nohup "$bin" \
    --bind "0.0.0.0:$RELAY_PORT" \
    --openai-base-url "$FINANCE_API_URL" \
    > "$LOG_DIR/nemo-relay.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/nemo-relay.pid"

  for _ in {1..20}; do
    if curl -fsS "http://127.0.0.1:$RELAY_PORT/v1/models" \
      -H "Authorization: Bearer $FINANCE_API_KEY" >/dev/null 2>&1; then
      log "NeMo Relay is reachable"
      return
    fi
    if ! kill -0 "$(cat "$LOG_DIR/nemo-relay.pid")" 2>/dev/null; then
      sed -n '1,120p' "$LOG_DIR/nemo-relay.log" >&2 || true
      die "NeMo Relay exited during startup"
    fi
    sleep 1
  done

  sed -n '1,120p' "$LOG_DIR/nemo-relay.log" >&2 || true
  die "NeMo Relay did not become reachable on 127.0.0.1:$RELAY_PORT"
}

build_ui() {
  if [[ "$SKIP_BUILD" == "1" ]]; then
    log "skipping UI build because FINANCE_SKIP_BUILD=1"
    return
  fi

  require npm
  if [[ ! -d node_modules ]]; then
    log "installing UI dependencies"
    npm install
  fi

  log "building UI"
  npm run build
}

start_ui() {
  require python3
  stop_pid_file "$LOG_DIR/finance-ui.pid"

  log "starting finance UI on 0.0.0.0:$UI_PORT through Hermes"
  nohup python3 scripts/finance_ui_server.py \
    --env-file "$ENV_FILE" \
    --host 0.0.0.0 \
    --port "$UI_PORT" \
    --api-url "$HERMES_API_URL" \
    --auth-env FINANCE_API_KEY \
    --model "$FINANCE_MODEL" \
    --upstream-label "Hermes + Relay + Phoenix" \
    --phoenix-url "http://127.0.0.1:$PHOENIX_PORT/graphql" \
    > "$LOG_DIR/finance-ui.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/finance-ui.pid"

  for _ in {1..20}; do
    if curl -fsS "http://127.0.0.1:$UI_PORT/health" >/dev/null 2>&1; then
      log "finance UI is reachable"
      return
    fi
    if ! kill -0 "$(cat "$LOG_DIR/finance-ui.pid")" 2>/dev/null; then
      sed -n '1,120p' "$LOG_DIR/finance-ui.log" >&2 || true
      die "finance UI exited during startup"
    fi
    sleep 1
  done

  sed -n '1,120p' "$LOG_DIR/finance-ui.log" >&2 || true
  die "finance UI did not become reachable on 127.0.0.1:$UI_PORT"
}

verify_chat_and_trace() {
  log "sending one chat request through UI -> Hermes"
  python3 - "$UI_PORT" "$FINANCE_MODEL" <<'PY'
import json
import sys
import urllib.request

port, model = sys.argv[1:3]
body = json.dumps(
    {
        "model": model,
        "stream": False,
        "max_tokens": 256,
        "reasoning_effort": "medium",
        "messages": [
            {"role": "system", "content": "You are a concise financial assistant."},
            {"role": "user", "content": "Reply with: setup check complete."},
        ],
    }
).encode()
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/chat/completions",
    data=body,
    headers={"Content-Type": "application/json", "X-Finance-Run-Id": "setup-check"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=120) as response:
    payload = json.load(response)
message = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
if "setup check complete" not in message.lower():
    raise SystemExit(f"unexpected chat response: {message!r}")
print(message)
PY

  log "checking Phoenix summary"
  python3 - "$UI_PORT" <<'PY'
import json
import sys
import urllib.request
from datetime import datetime, timezone

port = sys.argv[1]
with urllib.request.urlopen(
    f"http://127.0.0.1:{port}/api/phoenix/recent", timeout=20
) as response:
    payload = json.load(response)
spans = payload.get("spans", [])
if not spans:
    raise SystemExit("Phoenix returned no spans")
latest = spans[0]
started = latest.get("started_at", "")
print(f"latest span: {latest.get('project')} {latest.get('kind')} {latest.get('name')} {started}")
if not started:
    raise SystemExit("latest Phoenix span has no timestamp")
dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
age = datetime.now(timezone.utc) - dt
if age.total_seconds() > 300:
    raise SystemExit(f"latest Phoenix span is stale: {started}")
PY
}

print_summary() {
  cat <<EOF

Financial assistant demo is running.

Brev-side services:
  UI:      http://127.0.0.1:${UI_PORT}
  Hermes:  ${HERMES_API_URL}
  Relay:   http://127.0.0.1:${RELAY_PORT}
  Phoenix: http://127.0.0.1:${PHOENIX_PORT}

Logs:
  $LOG_DIR/finance-ui.log
  $LOG_DIR/nemo-relay.log

From your local machine, run:
  bash examples/financial-analyst-hermes/scripts/forward-brev-demo.sh financial-assistant-agent

Then open:
  UI:      http://127.0.0.1:${UI_PORT}
  Phoenix: http://127.0.0.1:${PHOENIX_PORT}

EOF
}

load_env
start_phoenix
start_relay
build_ui
start_ui
verify_chat_and_trace
print_summary
