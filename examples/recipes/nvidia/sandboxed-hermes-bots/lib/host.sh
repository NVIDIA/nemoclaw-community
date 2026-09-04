# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Host side of a bot: a Hermes profile on this machine whose "model" is the
# bot's sandbox api_server. Hermes Desktop lists host profiles as Bots; every
# turn it sends to this profile executes inside the sandbox.
#
# Whether the roster also needs a host-side gateway per profile is decided by
# HOST_GATEWAY (auto|on|off). "auto" follows what Task 0 of the plan found.

: "${HOST_GATEWAY:=on}"

host_profile_state() {
  hermes profile list 2>/dev/null | strip_ansi | awk -v n="$1" '$1==n{print $3}' | head -1
}

# host_profile_ensure NAME PORT KEY SOUL(optional)
# A host profile with our bot's name that this tool did not create belongs to
# the operator. Refuse to reconfigure or delete it.
_profile_marker() { printf '%s/.hermes/profiles/%s/.swarm-owner' "$HOME" "$1"; }
host_profile_owned() { [[ -f "$(_profile_marker "$1")" ]]; }

host_profile_ensure() {
  local name="$1" port="$2" key="$3" soul="$4"
  if hermes profile list 2>/dev/null | strip_ansi | awk '{print $1}' | grep -qx "$name"; then
    if ! host_profile_owned "$name"; then
      # Legacy adoption: the profile already points at this bot's sandbox port.
      if grep -qs "base_url: http://$HOST_API_ADDR:$port/v1" "$HOME/.hermes/profiles/$name/config.yaml"; then
        touch "$(_profile_marker "$name")"
      else
        die "a Hermes profile named $name already exists and was not created by this deployment; refusing to reconfigure it"
      fi
    fi
  else
    hermes profile create "$name" >/dev/null 2>&1 || die "could not create host profile $name"
    touch "$(_profile_marker "$name")"
  fi
  local prov
  prov=$(jq -cn --arg url "http://$HOST_API_ADDR:$port/v1" \
    '{name:"sandbox", base_url:$url, key_env:"SANDBOX_API_KEY", models:["hermes-agent"], default_model:"hermes-agent"}')
  hermes -p "$name" config set providers.sandbox "$prov" >/dev/null 2>&1
  hermes -p "$name" config set model.provider sandbox >/dev/null 2>&1
  hermes -p "$name" config set model.default hermes-agent >/dev/null 2>&1
  # The shim is itself a Hermes agent. With supports_vision off it strips
  # image parts before they reach the sandbox and leaves a text note with a
  # host path, which is useless in there. Always pass images through: whether
  # this bot can see is decided by the model config INSIDE the sandbox, and a
  # text bot that receives the image can forward it to a teammate that can.
  hermes -p "$name" config set model.supports_vision true >/dev/null 2>&1
  # The shim's "main model" is the bot. Auxiliary calls that default to the
  # main model (title generation, and compression if it ever triggers) would
  # each become a second full agent turn inside the sandbox, with tools and
  # without the image. Title generation fires on every message; turn it off.
  hermes -p "$name" config set auxiliary.title_generation.enabled false >/dev/null 2>&1
  hermes -p "$name" config set model.base_url "http://$HOST_API_ADDR:$port/v1" >/dev/null 2>&1
  hermes -p "$name" config set model.max_tokens "$INFERENCE_MAX_TOKENS" >/dev/null 2>&1
  hermes -p "$name" config set model.context_length "$INFERENCE_CONTEXT_LENGTH" >/dev/null 2>&1
  local envf="$HOME/.hermes/profiles/$name/.env"
  touch "$envf"; chmod 600 "$envf"
  sed_delete '^SANDBOX_API_KEY=' "$envf"
  printf 'SANDBOX_API_KEY=%s\n' "$key" >> "$envf"
  [[ -n "$soul" && -f "$soul" ]] && cp "$soul" "$HOME/.hermes/profiles/$name/SOUL.md"
  host_dropbox_ensure "$name"
  ok "host profile $name -> $HOST_API_ADDR:$port"

  if [[ "$HOST_GATEWAY" == on ]]; then
    host_gateway_start "$name"
  fi
}

# Dropped videos. Desktop attaches a dropped file as @file:/host/path, which
# means nothing in a sandbox. The dropbox plugin, installed in every host shim
# when a vss bot is in the fleet, uploads the clip into that bot's
# /sandbox/videos before the turn is forwarded and tells the bot the name.
# Host code, host tool (openshell sandbox upload), one target, videos only.
# Content-hashed like the sandbox plugins; removed when no vss bot exists.
host_dropbox_ensure() {
  local name="$1" vss="" b pdir dst envf want have
  for b in $(bot_list); do [[ "$(bot_short "$b")" == vss ]] && vss=$(sandbox_of "$b"); done
  pdir="$HOME/.hermes/profiles/$name/plugins"; dst="$pdir/dropbox"
  envf="$HOME/.hermes/profiles/$name/.env"
  sed_delete '^SWARM_VSS_SANDBOX=' "$envf"
  if [[ -z "$vss" || "$(bot_short "$name")" == vss ]]; then
    rm -rf "$dst"; return 0
  fi
  printf 'SWARM_VSS_SANDBOX=%s\n' "$vss" >> "$envf"
  want=$(cat "$SWARM_ROOT/plugins/dropbox/plugin.yaml" "$SWARM_ROOT/plugins/dropbox/__init__.py" > /tmp/dropbox.$$ && sha16 /tmp/dropbox.$$; rm -f /tmp/dropbox.$$)
  have=$(cat "$dst/.hash" 2>/dev/null || true)
  if [[ "$want" != "$have" ]]; then
    mkdir -p "$pdir"; rm -rf "$dst"; cp -R "$SWARM_ROOT/plugins/dropbox" "$dst"
    printf '%s' "$want" > "$dst/.hash"
    hermes -p "$name" plugins enable dropbox >/dev/null 2>&1 || true
    dim "dropbox plugin -> $name (videos land in $vss:/sandbox/videos)"
    # A running host gateway loaded plugins at start; cycle it so this lands.
    if [[ "$(host_profile_state "$name")" == running ]]; then
      host_gateway_stop "$name"; host_gateway_start "$name"
    fi
  fi
}

# The profile shows `running` in `hermes profile list` only when a gateway for
# it runs on this host. Login shell + setsid so it survives the SSH session.
host_gateway_start() {
  local name="$1" i st
  st=$(host_profile_state "$name")
  [[ "$st" == running ]] && { dim "host gateway for $name already running"; return 0; }
  rm -f "$HOME/.hermes/profiles/$name"/gateway.{pid,lock}
  daemonize "$(bot_log "$name" host-gateway)" hermes -p "$name" gateway run
  for ((i = 0; i < 12; i++)); do
    sleep 5
    [[ "$(host_profile_state "$name")" == running ]] && { ok "host gateway for $name running"; return 0; }
  done
  warn "profile $name still '$(host_profile_state "$name")'; log: $(bot_log "$name" host-gateway)"
}

host_gateway_stop() {
  local name="$1" pidf="$HOME/.hermes/profiles/$name/gateway.pid" pid
  hermes -p "$name" gateway stop >/dev/null 2>&1 || true
  # gateway.pid holds a JSON record, not a bare pid.
  if [[ -f "$pidf" ]]; then
    pid=$(python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1])); print(d.get("pid") or "")
except Exception:
    print(open(sys.argv[1]).read().strip())' "$pidf" 2>/dev/null | tr -dc '0-9')
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  fi
  pkill_pattern "hermes -p $name gateway run"
  pkill_pattern "profile $name serve"
}

host_profile_remove() {
  local name="$1"
  if hermes profile list 2>/dev/null | strip_ansi | awk '{print $1}' | grep -qx "$name" && ! host_profile_owned "$name"; then
    warn "host profile $name was not created by this deployment; leaving it"
    return 0
  fi
  host_gateway_stop "$name"
  if hermes profile delete -y "$name" >/dev/null 2>&1; then ok "host profile $name deleted"
  else rm -rf "$HOME/.hermes/profiles/$name"; dim "host profile dir removed"; fi
}

host_desktop_hint() {
  if is_macos; then
    cat <<EOF

  Hermes Desktop (this Mac)
    Quit and reopen the app. The bots above appear in the Bots roster under
    Local. Seat them in a group chat and @mention them.
EOF
    return
  fi
  # Remote host: the address the Desktop should SSH to, from the default route.
  local ip; ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -1)
  [[ -n "$ip" ]] || ip=$(host_reach_addr)
  cat <<EOF

  Hermes Desktop
    Settings -> Connections -> Add connection -> SSH: $(whoami)@${ip:-<this host>}
    Then quit and reopen the app; every bot above appears in the Bots roster.
    Seat them in a group chat and @mention them.
EOF
}
