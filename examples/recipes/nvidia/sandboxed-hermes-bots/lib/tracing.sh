# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Tracing: NeMo Relay (bundled in Hermes) -> OpenTelemetry collector on the
# host -> debug log, plus LangSmith when a key file is present.

COLLECTOR_NAME=swarm-otel
COLLECTOR_IMAGE=otel/opentelemetry-collector-contrib:0.145.0

_collector_config() { printf '%s/relay/otel-collector.yaml' "$SWARM_STATE"; }

# Render the collector config. Done in python so ${env:...} style strings are
# never touched by a shell or sed.
_collector_render() {
  local out; out=$(_collector_config)
  local ls_block="" exporters="debug"
  if [[ -n "$LANGSMITH_KEY_FILE" && -f "$LANGSMITH_KEY_FILE" ]]; then
    ls_block=$(cat <<EOF
  otlphttp/langsmith:
    endpoint: $LANGSMITH_ENDPOINT
    headers:
      x-api-key: "\${env:LANGSMITH_API_KEY}"
      Langsmith-Project: "$LANGSMITH_PROJECT"
EOF
)
    exporters="debug, otlphttp/langsmith"
  fi
  LS_BLOCK="$ls_block" EXPORTERS="$exporters" python3 - "$SWARM_ROOT/observability/otel-collector-config.yaml.tmpl" "$out" <<'PY'
import os, sys
src, dst = sys.argv[1], sys.argv[2]
t = open(src).read()
t = t.replace("__OTLP_PORT__", os.environ["OTLP_PORT"])
t = t.replace("__LANGSMITH_EXPORTER__", os.environ["LS_BLOCK"])
t = t.replace("__EXPORTERS__", os.environ["EXPORTERS"])
open(dst, "w").write(t)
PY
  printf '%s' "$out"
}

collector_running() { [[ "$(docker inspect -f '{{.State.Running}}' "$COLLECTOR_NAME" 2>/dev/null)" == true ]]; }

# Ensure the collector runs with the current config. Recreated when the
# rendered config changes (e.g. a LangSmith key appeared).
tracing_collector_ensure() {
  local cfg; cfg=$(_collector_render)
  local want have
  want=$(sha16 "$cfg")
  have=$(docker inspect -f '{{index .Config.Labels "swarm.config"}}' "$COLLECTOR_NAME" 2>/dev/null || true)
  if collector_running && [[ "$have" == "$want" ]]; then
    ok "collector $COLLECTOR_NAME running on $BRIDGE_IP:$OTLP_PORT"
    return 0
  fi
  docker rm -f "$COLLECTOR_NAME" >/dev/null 2>&1 || true
  # Bind the OTLP port on the bridge only, so sandboxes reach it and the LAN
  # does not. On macOS the bridge is inside the Colima/Docker Desktop VM and is
  # not a host interface, so bind to all VM interfaces instead; the VM itself is
  # not exposed to the LAN.
  local otlp_bind="$BRIDGE_IP:$OTLP_PORT:$OTLP_PORT"
  is_macos && otlp_bind="$OTLP_PORT:$OTLP_PORT"
  # bash 3.2 (macOS) treats an empty array as unset under `set -u`.
  local key_env=""
  if [[ -n "$LANGSMITH_KEY_FILE" && -f "$LANGSMITH_KEY_FILE" ]]; then
    key_env="LANGSMITH_API_KEY=$(read_secret "$LANGSMITH_KEY_FILE")"
  fi
  docker run -d --name "$COLLECTOR_NAME" --restart unless-stopped \
    --label "swarm.config=$want" \
    -p "$otlp_bind" -p "127.0.0.1:${OTLP_METRICS_PORT:-8889}:8888" \
    ${key_env:+-e "$key_env"} \
    -v "$cfg:/etc/otelcol-contrib/config.yaml:ro" \
    "$COLLECTOR_IMAGE" --config /etc/otelcol-contrib/config.yaml >/dev/null \
    || die "collector failed to start (docker logs $COLLECTOR_NAME)"
  # Probe from the host side. On macOS the bridge is inside the VM, so probe
  # loopback (the same publish covers both).
  local probe="$BRIDGE_IP"; is_macos && probe=127.0.0.1
  local i
  for ((i = 0; i < 20; i++)); do
    [[ "$(http_code "http://$probe:$OTLP_PORT/v1/traces" -X POST -H 'Content-Type: application/json' -d '{}')" =~ ^(200|400|415)$ ]] \
      && { ok "collector listening on $BRIDGE_IP:$OTLP_PORT (sandbox side)"; return 0; }
    sleep 2
  done
  die "collector not answering on $probe:$OTLP_PORT (docker logs $COLLECTOR_NAME)"
}

# Per bot: relay-plugins.toml + env var + egress policy. Caller restarts the gateway.
tracing_enable_bot() {
  local name="$1" sb toml pol
  sb=$(sandbox_of "$name")
  toml="$SWARM_STATE/relay/$name.relay-plugins.toml"
  sed -e "s|__OTLP_PORT__|$OTLP_PORT|" -e "s|__BOT__|$name|g" \
      -e "s|__NAMESPACE__|$LANGSMITH_PROJECT|" -e "s|__HOSTNAME__|$(hostname)|" \
      "$SWARM_ROOT/observability/relay-plugins.toml.tmpl" > "$toml"
  sandbox_put "$sb" "$toml" /sandbox/.hermes/relay-plugins.toml
  sbx "$sb" "sed -i '/^HERMES_NEMO_RELAY_PLUGINS_TOML=/d' /sandbox/.hermes/.env
echo 'HERMES_NEMO_RELAY_PLUGINS_TOML=/sandbox/.hermes/relay-plugins.toml' >> /sandbox/.hermes/.env; echo ENV-OK" 60 | grep -q ENV-OK \
    || die "could not set relay env in $sb"
  pol="$SWARM_STATE/policies/$sb-otlp.yaml"
  sed "s|__OTLP_PORT__|$OTLP_PORT|" "$SWARM_ROOT/policies/otlp-export.yaml" > "$pol"
  policy_add "$sb" "$pol"
  ok "relay config written for $name"
  # The gateway reads the env at start; restart so this run exports.
  bot_start "$name" "$(bot_port "$name")" >/dev/null
}

# True when Relay plugins came up in the bot's Hermes process. The line is
# logged at INFO by agent.relay_runtime, which lands in Hermes' own
# /sandbox/.hermes/logs/agent.log inside the sandbox, not in the stderr we
# capture on the host and not in gateway.log.
tracing_bot_active() {
  sbx "$(sandbox_of "$1")" 'grep -q "Relay plugins are active" /sandbox/.hermes/logs/agent.log && echo ACTIVE' 40 \
    | grep -q ACTIVE
}

# Exporter counters from the collector: "sent failed"
tracing_counts() {
  curl -s --max-time 5 "http://127.0.0.1:${OTLP_METRICS_PORT:-8889}/metrics" 2>/dev/null | awk '
    /^otelcol_exporter_sent_spans/ {s+=$NF}
    /^otelcol_exporter_send_failed_spans/ {f+=$NF}
    END {printf "%d %d\n", s, f}'
}

# Recent spans for one bot from the collector's debug exporter.
tracing_show() {
  local name="$1"
  collector_running || die "collector not running (swarm up)"
  docker logs --tail 4000 "$COLLECTOR_NAME" 2>&1 \
    | awk -v b="$name" '
        /^ResourceSpans|^Resource attributes/ {show=0}
        /agent.name: Str\(/ && index($0, "(" b ")") {show=1}
        /^Span #/ {inspan=show}
        inspan && /^ *(Name|Kind|Start time|End time|Status code)/ {print}
        inspan && /^Span #/ {print "  ----"}' | tail -60
}
