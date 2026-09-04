# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Mesh: every bot can message every other bot. For each pair A,B:
#   - A's sandbox knows B as a peer (hermes peer add, with B's api key)
#   - A's sandbox policy allows egress to B's api port on the bridge
#   - the `teammates` plugin (message_teammate / list_teammates) is installed
# and the same in the other direction. Registration happens INSIDE the sandbox
# because that is where the agent loop runs and reads its config.

# Peers a bot's sandbox currently knows about.
mesh_peers_of() {
  local sb; sb=$(sandbox_of "$1")
  [[ "$(sandbox_phase "$sb")" == Ready ]] || return 0
  # Output is one peer per line: "<name>\t<url>\t[key set] — <note>", no header.
  sbx "$sb" '$H -m hermes_cli.main peer list 2>/dev/null' 60 | strip_ansi \
    | awk -F'\t' 'NF>=2 && $2 ~ /^http/ {print $1}' || true
}

# Install the teammates plugin into a sandbox (one tarball; per-file writes
# drop everything after the first, and args are capped near 32KB). Keyed on
# the plugin's content hash, so editing the plugin and re-running `swarm up`
# updates every bot instead of skipping the ones that already have a copy.
_mesh_install_plugin() {
  local sb="$1" tgz b64 want have
  want=$(cd "$SWARM_ROOT/plugins/teammates" && cat plugin.yaml __init__.py schemas.py tools.py > /tmp/teammates.$$ && sha16 /tmp/teammates.$$; rm -f /tmp/teammates.$$)
  have=$(sbx "$sb" 'cat /sandbox/.hermes/plugins/teammates/.swarm-hash 2>/dev/null' 60 | tail -1)
  [[ "$have" == "$want" ]] && return 0
  tgz=$(mktemp /tmp/teammates.XXXXXX.tgz)
  tar czf "$tgz" -C "$SWARM_ROOT/plugins" --exclude=__pycache__ teammates
  b64=$(b64 "$tgz"); rm -f "$tgz"
  sbx "$sb" "mkdir -p /sandbox/.hermes/plugins && rm -rf /sandbox/.hermes/plugins/teammates && printf '%s' '$b64' | base64 -d | tar xzf - -C /sandbox/.hermes/plugins
printf '%s' '$want' > /sandbox/.hermes/plugins/teammates/.swarm-hash
\$H -m hermes_cli.main plugins enable teammates >/dev/null 2>&1 || true
test -f /sandbox/.hermes/plugins/teammates/plugin.yaml && echo PLUGIN-OK" 180 | grep -q PLUGIN-OK \
    || die "installing teammates plugin into $sb failed"
  [[ -n "$have" ]] && dim "teammates plugin updated in $sb"
  return 0
}

# _mesh_link A B: make A able to reach B.
_mesh_link() {
  local a="$1" b="$2" sb_a port_b key_b
  sb_a=$(sandbox_of "$a"); port_b=$(bot_port "$b") || return 0
  key_b=$(read_secret "$(bot_key_file "$b")")
  sbx "$sb_a" "\$H -m hermes_cli.main peer add '$b' --url 'http://host.openshell.internal:$port_b' --key '$key_b' --note '$b' >/dev/null 2>&1 && echo PEER-OK" 120 \
    | grep -q PEER-OK || warn "peer add $b inside $sb_a failed"
  policy_add_peer "$sb_a" "$b" "$port_b"
}

# Bring every pair up to date. Idempotent; peer add updates in place, and
# policy-add of an existing group is a no-op.
mesh_sync() {
  local a b n line
  local bots=(); while IFS= read -r line; do [[ -n "$line" ]] && bots+=("$line"); done < <(bot_list)
  n=${#bots[@]}
  (( n < 2 )) && { dim "mesh: fewer than two bots"; return 0; }
  for a in "${bots[@]}"; do
    [[ "$(sandbox_phase "$(sandbox_of "$a")")" == Ready ]] || continue
    _mesh_install_plugin "$(sandbox_of "$a")"
    for b in "${bots[@]}"; do
      [[ "$a" == "$b" ]] && continue
      _mesh_link "$a" "$b"
    done
    ok "$a knows: $(mesh_peers_of "$a" | tr '\n' ' ')"
  done
  # Gateways read peer config at startup; restart so message_teammate sees new peers.
  for a in "${bots[@]}"; do
    [[ "$(sandbox_phase "$(sandbox_of "$a")")" == Ready ]] || continue
    bot_start "$a" "$(bot_port "$a")" >/dev/null
  done
  for a in "${bots[@]}"; do
    bot_wait_api "$a" "$(bot_port "$a")" "$(read_secret "$(bot_key_file "$a")")" >/dev/null || warn "$a api not back yet"
  done
  ok "mesh: $n bots, $((n * (n - 1))) directed links"
}

# Remove a departed bot from everyone else's peer list. The policy group that
# allowed its port stays (policy-add cannot remove); the port is dead anyway.
mesh_forget() {
  local gone="$1" a
  for a in $(bot_list); do
    [[ "$a" == "$gone" ]] && continue
    sbx "$(sandbox_of "$a")" "\$H -m hermes_cli.main peer remove '$gone' >/dev/null 2>&1; echo ok" 60 >/dev/null
  done
}
