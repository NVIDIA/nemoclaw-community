# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Preflight: every check prints PASS or FAIL with the fix. Returns non-zero if
# anything failed. Nothing here changes the host.

_pf_pass=0; _pf_fail=0
pf_ok()   { ok "$*";   _pf_pass=$((_pf_pass + 1)); }
pf_fail() { fail "$*"; _pf_fail=$((_pf_fail + 1)); }

preflight_run() {
  _pf_pass=0; _pf_fail=0
  local c

  for c in docker openshell nemoclaw hermes curl jq python3 openssl; do
    if command -v "$c" >/dev/null 2>&1; then pf_ok "$c on PATH"
    else pf_fail "$c not found (openshell/nemoclaw/hermes install to ~/.local/bin; use a login shell)"; fi
  done
  if command -v timeout >/dev/null 2>&1; then pf_ok "timeout on PATH"
  elif command -v gtimeout >/dev/null 2>&1; then pf_ok "gtimeout on PATH (macOS coreutils)"
  else pf_fail "no timeout command (macOS: brew install coreutils)"; fi

  if docker info >/dev/null 2>&1; then pf_ok "docker daemon reachable"
  else pf_fail "docker daemon not reachable (is this user in the docker group?)"; fi

  local hv
  hv=$(hermes --version 2>/dev/null | head -1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' || true)
  if [[ -n "$hv" ]] && [[ "$(printf '%s\n' v0.21.0 "$hv" | sort -V | head -1)" == v0.21.0 ]]; then
    pf_ok "host hermes $hv (>= v0.21.0)"
  else
    pf_fail "host hermes ${hv:-missing}; need >= v0.21.0 (hermes update)"
  fi

  # The bridge is where sandboxes reach the host (host.openshell.internal) and
  # where api_servers are published. On Linux it is a host interface; on macOS
  # it lives inside the Colima/Docker Desktop VM, so ask Docker rather than ip.
  local detected
  detected=$(docker network inspect openshell-docker -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)
  if [[ -n "$detected" && "$detected" != "$BRIDGE_IP" ]]; then
    pf_fail "BRIDGE_IP=$BRIDGE_IP but the openshell-docker network gateway is $detected; set BRIDGE_IP=$detected in swarm.env"
  elif [[ -n "$detected" ]]; then pf_ok "openshell bridge $BRIDGE_IP (docker network openshell-docker)"
  elif ip -4 addr show 2>/dev/null | grep -q " $BRIDGE_IP/"; then pf_ok "openshell bridge $BRIDGE_IP present"
  else pf_fail "no openshell-docker network and no interface has $BRIDGE_IP (is OpenShell running? openshell sandbox list)"; fi

  if openshell sandbox list >/dev/null 2>&1; then pf_ok "openshell control plane answers"
  else pf_fail "openshell sandbox list failed"; fi

  if [[ -f "$INFERENCE_KEY_FILE" ]]; then
    local mode; mode=$(file_mode "$INFERENCE_KEY_FILE")
    if [[ "$mode" == 600 ]]; then pf_ok "inference key file mode 600"
    else pf_fail "inference key file $INFERENCE_KEY_FILE is mode $mode; chmod 600 it"; fi
    local code models
    models=$(curl -s --max-time 15 -H "Authorization: Bearer $(tr -d '\r\n' < "$INFERENCE_KEY_FILE")" \
               "$INFERENCE_BASE_URL/models" 2>/dev/null || true)
    code=$(http_code "$INFERENCE_BASE_URL/models" -H "Authorization: Bearer $(tr -d '\r\n' < "$INFERENCE_KEY_FILE")")
    if [[ "$code" == 200 ]]; then pf_ok "inference endpoint auth ($INFERENCE_BASE_URL) 200"
    else pf_fail "inference endpoint returned $code (401 = bad key, 000 = unreachable from this host)"; fi
    # Every distinct model any bot uses (INFERENCE_MODEL plus per-bot overrides).
    local m seen=" "
    for m in "$INFERENCE_MODEL" $(compgen -v | grep '^INFERENCE_MODEL_' | while read -r v; do printf '%s\n' "${!v}"; done); do
      [[ "$seen" == *" $m "* ]] && continue; seen+="$m "
      if printf '%s' "$models" | jq -e --arg m "$m" '.data[]? | select(.id==$m)' >/dev/null 2>&1; then
        pf_ok "model $m listed by endpoint"
      else pf_fail "model $m not in $INFERENCE_BASE_URL/models"; fi
    done
  else
    pf_fail "inference key file missing: $INFERENCE_KEY_FILE (umask 077; echo TOKEN > it)"
  fi

  local free_gb
  free_gb=$(df -Pk / | awk 'NR==2 {printf "%d", $4/1048576}')
  if [[ "${free_gb:-0}" -ge 20 ]]; then pf_ok "disk ${free_gb}G free"
  else pf_fail "only ${free_gb:-?}G free on /; need 20G for the image"; fi

  if [[ -n "${VSS_BASE_URL:-}" ]]; then
    # As the host sees it: host.openshell.internal is the bridge address.
    local vurl="${VSS_BASE_URL/host.openshell.internal/$BRIDGE_IP}" vcode
    vcode=$(http_code "$vurl/v1/health/ready")
    if [[ "$vcode" == 200 ]]; then pf_ok "RT-VLM ready at $vurl"
    else pf_fail "RT-VLM at $vurl returned $vcode (000 = not running; see examples/README.md)"; fi
  fi

  if [[ "$TRACING" == "on" ]]; then
    if [[ -n "$LANGSMITH_KEY_FILE" && -f "$LANGSMITH_KEY_FILE" ]]; then pf_ok "tracing on; LangSmith export enabled (key file present)"
    else pf_ok "tracing on; local collector only (no LangSmith key file)"; fi
  else
    dim "tracing off"
  fi

  printf '\n  %d passed, %d failed\n' "$_pf_pass" "$_pf_fail"
  (( _pf_fail == 0 ))
}
