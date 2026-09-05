# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Health ladder for `swarm status`. Each rung is a real probe, ordered so the
# first failure names the layer at fault:
#   sandbox Ready -> api_server 200 -> chat turn -> relay active -> peers

_v_pass=0; _v_fail=0
v_ok()   { ok "$*";   _v_pass=$((_v_pass + 1)); }
v_fail() { fail "$*"; _v_fail=$((_v_fail + 1)); }

verify_bot() {
  local name="$1" sb port key code reply
  sb=$(sandbox_of "$name")
  port=$(bot_port "$name" || true)
  key=$(read_secret "$(bot_key_file "$name")" 2>/dev/null || true)
  printf '  %s%s%s\n' "$C_BOLD" "$name" "$C_OFF"

  if [[ "$(sandbox_phase "$sb")" == Ready ]]; then v_ok "sandbox $sb Ready"
  else v_fail "sandbox $sb: $(sandbox_phase "$sb")"; return 1; fi

  [[ -n "$port" && -n "$key" ]] || { v_fail "no port/key in $SWARM_STATE/keys"; return 1; }
  code=$(http_code "http://$HOST_API_ADDR:$port/v1/models" -H "Authorization: Bearer $key")
  if [[ "$code" == 200 ]]; then v_ok "api_server :$port 200"
  else v_fail "api_server :$port $code (000 = forward down, 401 = key mismatch)"; return 1; fi

  reply=$(timeout 240 hermes -p "$name" chat -q "Reply with exactly: $name-OK" 2>/dev/null | grep -ao "$name-OK" | head -1)
  if [[ "$reply" == "$name-OK" ]]; then v_ok "chat turn through the sandbox"
  else v_fail "no clean reply (hermes -p $name chat -q ...); gateway log: $(bot_log "$name" gateway)"; fi

  if [[ "$TRACING" == on ]]; then
    if tracing_bot_active "$name"; then v_ok "relay plugins active"
    else v_fail "relay not active (no activation line in /sandbox/.hermes/logs/agent.log of $(sandbox_of "$name"))"; fi
  fi

  local st; st=$(host_profile_state "$name")
  if [[ "$HOST_GATEWAY" == on ]]; then
    if [[ "$st" == running ]]; then v_ok "host profile running (visible to Desktop)"
    else v_fail "host profile $st (Desktop roster will not list it)"; fi
  fi

  local peers; peers=$(mesh_peers_of "$name" | tr '\n' ' ')
  dim "peers: ${peers:-none}"
}

verify_all() {
  _v_pass=0; _v_fail=0
  local b sent failed
  for b in $(bot_list); do verify_bot "$b" || true; done
  if [[ "$TRACING" == on ]]; then
    if collector_running; then
      read -r sent failed < <(tracing_counts)
      v_ok "collector: $sent spans exported, $failed failed"
    else v_fail "collector $COLLECTOR_NAME not running"; fi
  fi
  printf '\n  %d ok, %d failed\n' "$_v_pass" "$_v_fail"
  (( _v_fail == 0 ))
}
