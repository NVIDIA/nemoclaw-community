# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# One bot: sandbox + Hermes config + api_server + gateway + bridge forward.
# A bot is identified by its name; its sandbox is $(sandbox_of NAME) and its
# host profile is NAME.

# ── inventory ────────────────────────────────────────────────────────────────
# Bots are discovered from the key files this tool wrote, so the sandbox name
# can equal the bot name (SANDBOX_PREFIX may be empty) and other people's
# sandboxes on the same host are never touched.
bot_list() {
  local f
  for f in "$SWARM_STATE"/keys/*.key; do [[ -f "$f" ]] && basename "$f" .key; done | sort
}
bot_exists() { [[ -s "$(bot_key_file "$1")" ]] && sandbox_exists "$(sandbox_of "$1")"; }

bot_port() {
  local f; f=$(bot_port_file "$1")
  [[ -s "$f" ]] && tr -dc '0-9' < "$f"
}

# Next api port not held by any bot and not bound on the bridge.
_next_port() {
  local p="$API_PORT_BASE" used
  used=$(cat "$SWARM_STATE"/keys/*.port 2>/dev/null | tr '\n' ' ')
  while [[ " $used " == *" $p "* ]] || port_in_use "$p"; do p=$((p + 1)); done
  printf '%s' "$p"
}

# ── create ───────────────────────────────────────────────────────────────────
# bot_create NAME SOUL.md
bot_create() {
  local name="$1" soul="$2" sb port key pol
  [[ -f "$soul" ]] || die "soul file not found: $soul"
  sb=$(sandbox_of "$name")

  # Reuse a stored key and port on re-runs: a new key would invalidate every
  # peer registration other bots hold for this one.
  port=$(bot_port "$name" || true); [[ -n "$port" ]] || port=$(_next_port)
  printf '%s\n' "$port" > "$(bot_port_file "$name")"
  if [[ -s "$(bot_key_file "$name")" ]]; then key=$(read_secret "$(bot_key_file "$name")")
  else key=$(openssl rand -hex 32); (umask 077; printf '%s\n' "$key" > "$(bot_key_file "$name")"); fi
  dim "api port $port"

  pol=$(policy_render_base "$name")
  sandbox_create "$sb" "$pol"

  local ver
  ver=$(sbx "$sb" '$H -m hermes_cli.main --version 2>/dev/null | head -1' 60 | tail -1)
  [[ "$ver" == *"$(printf '%s' "$HERMES_REF" | sed 's/^v//')"* ]] || warn "sandbox Hermes reports: ${ver:-nothing} (image tag $HERMES_REF)"
  ok "hermes in sandbox: ${ver:-?}"

  bot_configure "$name" "$port" "$key" "$soul"
  bot_policy_extras "$name"
  bot_install_extras "$name"
  bot_start "$name" "$port"
  host_profile_ensure "$name" "$port" "$key" "$soul"
  [[ "$TRACING" == "on" ]] && tracing_enable_bot "$name"
  bot_wait_api "$name" "$port" "$key"
}

# Role-specific reach: policies/<bot>.yaml is an additive preset applied when
# present. This is how the researcher gets GitHub and the reviewer does not.
bot_policy_extras() {
  local name="$1" f
  f=$(bot_policy_file "$name")
  [[ -n "$f" ]] || return 0
  policy_add "$(sandbox_of "$name")" "$f"
  ok "extra policy applied: ${f#$SWARM_ROOT/}"
}

# Write model/provider, api_server, SOUL, and the inference key into the sandbox.
bot_configure() {
  local name="$1" port="$2" key="$3" soul="$4"
  bot_configure_model "$name" "$port" "$key"
  bot_write_soul "$name" "$soul"
  ok "model $(bot_model "$name"), api_server :$port, SOUL written"
}

# Model, endpoint, key, and api_server only. Safe to re-run: `swarm up` calls
# this on restore so editing swarm.env and re-running picks up a new model.
# bot_model NAME: the model this bot runs. INFERENCE_MODEL_<NAME> in swarm.env
# overrides INFERENCE_MODEL for one bot (name upper-cased, dashes to
# underscores, the same rule peer keys use). Same endpoint, same key.
bot_model() {
  local var="INFERENCE_MODEL_$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
  printf '%s' "${!var:-$INFERENCE_MODEL}"
}

# bot_vision NAME: "true" if INFERENCE_VISION_<NAME>=on (or INFERENCE_VISION=on
# for every bot), else "false". Hermes strips image parts for any model it
# cannot look up on models.dev, which is every model behind a custom endpoint,
# so a vision-capable model must be declared or the bot never sees a pixel.
bot_vision() {
  local var="INFERENCE_VISION_$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
  case "${!var:-${INFERENCE_VISION:-off}}" in on|true|yes|1) printf 'true' ;; *) printf 'false' ;; esac
}

bot_configure_model() {
  local name="$1" port="$2" key="$3" sb ikey model
  sb=$(sandbox_of "$name")
  ikey=$(read_secret "$INFERENCE_KEY_FILE")
  model=$(bot_model "$name")

  # A named provider block with key_env is the shape Hermes 0.21 resolves
  # reliably; `provider: custom` + OPENAI_API_KEY was rejected by the same
  # endpoint during testing.
  local prov
  prov=$(jq -cn --arg url "$INFERENCE_BASE_URL" --arg m "$model" \
    '{name:"inference", base_url:$url, key_env:"INFERENCE_API_KEY", models:[$m], default_model:$m}')

  sbx "$sb" "
set -e
\$H -m hermes_cli.main config set providers.inference '$prov' >/dev/null
\$H -m hermes_cli.main config set model.provider inference >/dev/null
\$H -m hermes_cli.main config set model.default '$model' >/dev/null
\$H -m hermes_cli.main config set model.supports_vision $(bot_vision "$name") >/dev/null
\$H -m hermes_cli.main config set model.base_url '$INFERENCE_BASE_URL' >/dev/null
\$H -m hermes_cli.main config set model.max_tokens $INFERENCE_MAX_TOKENS >/dev/null
\$H -m hermes_cli.main config set model.context_length $INFERENCE_CONTEXT_LENGTH >/dev/null
\$H -m hermes_cli.main config set gateway.platforms.api_server.enabled true >/dev/null
\$H -m hermes_cli.main config set gateway.platforms.api_server.extra.port $port >/dev/null
touch /sandbox/.hermes/.env; chmod 600 /sandbox/.hermes/.env
sed -i '/^API_SERVER_KEY=/d; /^INFERENCE_API_KEY=/d' /sandbox/.hermes/.env
printf 'API_SERVER_KEY=%s\nINFERENCE_API_KEY=%s\n' '$key' '$ikey' >> /sandbox/.hermes/.env
echo CONFIGURED" 300 | tail -1 | grep -q CONFIGURED || die "configuring $sb failed"
}

bot_write_soul() {
  local name="$1" soul="$2" sb body
  sb=$(sandbox_of "$name")
  body=$(cat "$soul"; printf '\n\n%s\n' "$(_soul_runtime_section "$name")")
  printf '%s' "$body" > "$SWARM_STATE/relay/$name.soul.md"
  sandbox_put "$sb" "$SWARM_STATE/relay/$name.soul.md" /sandbox/.hermes/SOUL.md
}

# What each teammate can do that this bot cannot. Generated from the fleet so
# it stays true as bots are added: a text bot learns that nemoclaw-vision can
# look at images and nemoclaw-vss can watch video, and is told to ask rather
# than apologise. Empty when there is nothing to say.
_soul_teammates_section() {
  local me="$1" b lines=""
  for b in $BOTS; do
    [[ "$b" == "$me" ]] && continue
    case "$(bot_short "$b")" in
      vision) [[ "$(bot_vision "$me")" == on ]] || lines+="- $b can look at images. If a message has an image attached and you cannot see it, do not say so and stop: send $b a message_teammate asking what is in it, then answer from their description with attribution.
" ;;
      vss)    lines+="- $b can watch video files and clips. For any question about what happens in a video, ask $b via message_teammate and work from their timestamped findings.
" ;;
    esac
  done
  [[ -n "$lines" ]] || return 0
  printf -- '- Ask a teammate for what you cannot do yourself:\n%s' "$lines" | sed 's/^- \(nemoclaw\)/  - \1/'
  printf -- '  Ask once: one message_teammate call, then wait for the reply. Do not fire two\n  asks at the same teammate in parallel; the second one arrives without the image.\n'
  # $lines ends in a newline that heredoc substitution strips; put it back so
  # the rule that follows starts on its own line.
  printf '\n'
}

_soul_runtime_section() {
  cat <<EOF
## Runtime
You are a NemoClaw bot: a Hermes agent running inside an NVIDIA OpenShell
sandbox named $(sandbox_of "$1"), managed by NemoClaw, traced by NeMo Relay.
The sandbox has its own kernel namespaces and deny-by-default egress; only
what your policy lists is reachable. When asked who or what you are, say so in
one sentence. If a tool cannot reach something, report the blocker plainly
rather than guessing around it.

## Rules
- Never invent a source, URL, number, or quote. Label inference as inference.
$(_soul_teammates_section "$1")- Give the result in this message rather than promising it later; a turn is one
  request and one reply.
EOF
}

# Start (or restart) the in-sandbox gateway and publish the api_server on the bridge.
bot_start() {
  local name="$1" port="$2" sb
  sb=$(sandbox_of "$name")
  # Always restart: the gateway reads API_SERVER_KEY and the Relay env at
  # startup, so a gateway started earlier can hold stale values.
  sbx "$sb" '$H -m hermes_cli.main gateway stop >/dev/null 2>&1 || true; pkill -f "hermes_cli.main gateway run" 2>/dev/null || true; rm -f /sandbox/.hermes/gateway.pid /sandbox/.hermes/gateway.lock; echo STOPPED' 90 >/dev/null
  pkill_pattern "sandbox exec -n $sb .* gateway run"
  daemonize "$(bot_log "$name" gateway)" openshell sandbox exec -n "$sb" --timeout 0 -- /bin/sh -c \
    'export HOME=/sandbox HERMES_HOME=/sandbox/.hermes; exec /sandbox/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run'
  # Forward: kill by exact port first so duplicates never accumulate.
  pkill_pattern "forward service --target-port $port "
  daemonize "$(bot_log "$name" forward)" openshell forward service --target-port "$port" --local "$HOST_API_ADDR:$port" "$sb"
  ok "gateway and bridge forward started"
}

bot_wait_api() {
  local name="$1" port="$2" key="$3" i code
  for ((i = 0; i < 24; i++)); do
    code=$(http_code "http://$HOST_API_ADDR:$port/v1/models" -H "Authorization: Bearer $key")
    [[ "$code" == 200 ]] && { ok "api_server 200 on $HOST_API_ADDR:$port"; return 0; }
    sleep 5
  done
  warn "api_server on :$port returned $code after 2 min; gateway log: $(bot_log "$name" gateway)"
  return 1
}

# After a reboot: sandbox exists, nothing is running. Bring it back.
bot_restore() {
  local name="$1" port key
  port=$(bot_port "$name") || die "no stored port for $name in $SWARM_STATE/keys"
  key=$(read_secret "$(bot_key_file "$name")")
  [[ "$(sandbox_phase "$(sandbox_of "$name")")" == Ready ]] || die "sandbox $(sandbox_of "$name") is not Ready"
  bot_configure_model "$name" "$port" "$key"
  dim "model $(bot_model "$name") via $INFERENCE_BASE_URL"
  # Re-write the soul and per-bot extras too: editing a soul or swarm.env's
  # VSS_* lines and re-running `swarm up` is how those changes land.
  bot_write_soul "$name" "$(bot_soul_file "$name")" 2>/dev/null || true
  bot_env_extras "$name"
  bot_files_extras "$name"
  bot_toolset_extras "$name"
  bot_start "$name" "$port"
  host_profile_ensure "$name" "$port" "$key" ""
  # Re-apply tracing every time: policy-add and the env write are idempotent,
  # and this is how a bot created with tracing off picks it up later.
  [[ "$TRACING" == "on" ]] && tracing_enable_bot "$name"
  bot_wait_api "$name" "$port" "$key" || true
}

# ── destroy ──────────────────────────────────────────────────────────────────
bot_destroy() {
  local name="$1" sb port
  sb=$(sandbox_of "$name")
  port=$(bot_port "$name" || true)
  log "removing bot $name"
  [[ -n "$port" ]] && pkill_pattern "forward service --target-port $port "
  pkill_pattern "sandbox exec -n $sb .* gateway run"
  host_profile_remove "$name"
  sandbox_delete "$sb"
  rm -f "$(bot_key_file "$name")" "$(bot_port_file "$name")" \
        "$SWARM_STATE/policies/$sb"*.yaml "$SWARM_STATE/policies/"*"-peer-$name.yaml" \
        "$SWARM_STATE/relay/$name."* "$SWARM_STATE/logs/$name-"*.log
  ok "bot $name removed"
}

# ── table ────────────────────────────────────────────────────────────────────
bot_table() {
  local json="${1:-}" b sb phase port peers gw
  if [[ "$json" == "--json" ]]; then
    printf '['
    local first=1
    for b in $(bot_list); do
      sb=$(sandbox_of "$b"); port=$(bot_port "$b" || true)
      (( first )) || printf ','; first=0
      jq -cn --arg n "$b" --arg sb "$sb" --arg ph "$(sandbox_phase "$sb")" --arg p "${port:-}" \
        --arg peers "$(mesh_peers_of "$b" | tr '\n' ' ')" \
        '{name:$n, sandbox:$sb, phase:$ph, api_port:($p|tonumber? // null), peers:($peers|split(" ")|map(select(.!="")))}'
    done
    printf ']\n'
    return
  fi
  printf '  %-12s %-16s %-7s %-6s %-9s %s\n' BOT SANDBOX PHASE API GATEWAY PEERS
  for b in $(bot_list); do
    sb=$(sandbox_of "$b"); port=$(bot_port "$b" || true); phase=$(sandbox_phase "$sb")
    gw=$(host_profile_state "$b")
    peers=$(mesh_peers_of "$b" | tr '\n' ' ')
    printf '  %-12s %-16s %-7s %-6s %-9s %s\n' "$b" "$sb" "$phase" "${port:--}" "$gw" "${peers:--}"
  done
}
