# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# OpenShell sandbox helpers.

# Phase of a sandbox ("Ready", "Error", ...) or empty if absent.
sandbox_phase() {
  openshell sandbox list 2>/dev/null | strip_ansi | awk -v n="$1" '$1==n{print $NF}'
}

sandbox_exists() { [[ -n "$(sandbox_phase "$1")" ]]; }

# Docker container backing a sandbox (for docker cp).
sandbox_container() { docker ps --format '{{.Names}}' | grep "^openshell-$1-" | head -1; }

# sandbox_create NAME POLICY.yaml
# `openshell sandbox create` has been seen to block long after the sandbox is
# Ready, so it is bounded and the readiness poll below is the real gate.
# Ownership. OpenShell has no label API for sandboxes, so a sandbox this tool
# created is marked twice: a file under $SWARM_STATE/owned/ (host side, mode
# 700 directory) and a marker file inside the sandbox. Both hold this state
# directory's persistent deployment token. A same-named sandbox that fails
# the check is someone else's, and every mutating path refuses it.
_owned_dir() { printf '%s/owned' "$SWARM_STATE"; }
sandbox_owned() {
  local sb="$1" f tok inside expected
  f="$(_owned_dir)/$sb"; [[ -s "$f" ]] || return 1
  tok=$(tr -d '\r\n' < "$f")
  inside=$(sbx "$sb" 'cat /sandbox/.hermes/.swarm-owner 2>/dev/null' 30 | tail -1)
  expected=$(deployment_owner_token)
  [[ "$tok" == "$expected" && "$inside" == "$expected" ]] && return 0

  # Migrate the old per-sandbox token only when both independently stored
  # copies still agree.  A one-sided marker never grants ownership.
  if [[ -n "$tok" && "$tok" == "$inside" ]]; then
    _sandbox_set_owner "$sb" "$expected" || return 1
    return 0
  fi
  return 1
}
_sandbox_set_owner() {
  local sb="$1" tok="$2" tmp
  mkdir -p "$(_owned_dir)"; chmod 700 "$(_owned_dir)"
  sbx "$sb" "printf '%s' '$tok' > /sandbox/.hermes/.swarm-owner && chmod 600 /sandbox/.hermes/.swarm-owner && echo OWN-OK" 60 \
    | grep -q OWN-OK || return 1
  tmp="$(_owned_dir)/.$sb.$$.$RANDOM"
  (umask 077; printf '%s\n' "$tok" > "$tmp")
  mv "$tmp" "$(_owned_dir)/$sb"
}
_sandbox_mark_owned() {
  local sb="$1"
  _sandbox_set_owner "$sb" "$(deployment_owner_token)" \
    || die "could not write ownership marker into $sb"
}

# One-time adoption for fleets built before ownership markers existed: the
# sandbox has no marker on either side, this tool holds its key and port, and
# the api_server inside answers to that key. Nothing else qualifies.
sandbox_adopt_legacy() {
  local sb="$1" name="$2" port key code
  [[ -s "$(_owned_dir)/$sb" ]] && return 1
  [[ -n "$(sbx "$sb" 'cat /sandbox/.hermes/.swarm-owner 2>/dev/null' 30 | tail -1)" ]] && return 1
  port=$(bot_port "$name" 2>/dev/null) || return 1
  [[ -s "$(bot_key_file "$name")" ]] || return 1
  key=$(read_secret "$(bot_key_file "$name")")
  # Probe from inside the candidate itself. A host-side forward could point at
  # a different process and must never be accepted as proof of ownership.
  code=$(sbx "$sb" "curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'Authorization: Bearer $key' http://127.0.0.1:$port/v1/models" 30 | tail -1)
  [[ "$code" == 200 ]] || return 1
  _sandbox_mark_owned "$sb"
  dim "adopted $sb: built by an earlier version of this tool, now marked as owned"
}

sandbox_create() {
  local sb="$1" pol="$2" i phase created=""
  if sandbox_exists "$sb"; then
    if sandbox_owned "$sb"; then
      dim "sandbox $sb exists ($(sandbox_phase "$sb")), created by this deployment"
    else
      die "a sandbox named $sb already exists and was not created by this deployment. Refusing to reconfigure it. Set SANDBOX_PREFIX in swarm.env to use different names, or remove it yourself if it is yours."
    fi
  else
    timeout 180 openshell sandbox create --name "$sb" --from "$(image_tag)" \
      --policy "$pol" --memory "$SANDBOX_MEMORY" --cpu "$SANDBOX_CPU" >/dev/null 2>&1 || true
    created=1
  fi
  for ((i = 0; i < 30; i++)); do
    phase=$(sandbox_phase "$sb")
    if [[ "$phase" == Ready ]]; then
      [[ -n "$created" ]] && _sandbox_mark_owned "$sb"
      ok "sandbox $sb Ready"; return 0
    fi
    [[ "$phase" == Error ]] && die "sandbox $sb entered Error; see: docker logs \$(docker ps -a --filter name=$sb -q | head -1)"
    sleep 6
  done
  die "sandbox $sb not Ready after 3 min (phase: ${phase:-none})"
}

# Returns non-zero while the sandbox still exists, so callers can stop before
# discarding the state needed to manage it.
sandbox_delete() {
  local sb="$1"
  sandbox_exists "$sb" || return 0
  sandbox_owned "$sb" || { fail "sandbox $sb is not owned by this deployment; refusing to delete it"; return 1; }
  timeout 180 openshell sandbox delete "$sb" >/dev/null 2>&1 || true
  local i
  for ((i = 0; i < 20; i++)); do
    sandbox_exists "$sb" || { ok "sandbox $sb deleted"; return 0; }
    sleep 3
  done
  fail "sandbox $sb still listed after delete (phase: $(sandbox_phase "$sb"))"
  return 1
}

# sbx SANDBOX SCRIPT [timeout_s]
# Run a shell snippet inside a sandbox with Hermes env set. Snippets over ~30KB
# are staged through a file because sandbox exec caps its argument size.
sbx() {
  local sb="$1" script="$2" t="${3:-300}"
  local pre='export HOME=/sandbox HERMES_HOME=/sandbox/.hermes PATH=/sandbox/.hermes/hermes-agent/venv/bin:/usr/local/bin:/usr/bin:/bin; H=/sandbox/.hermes/hermes-agent/venv/bin/python; '
  if (( ${#script} > 28000 )); then
    local b64 chunk f=/tmp/sbx-$RANDOM.sh
    b64=$(printf '%s' "$script" | b64)
    timeout 60 openshell sandbox exec -n "$sb" --timeout 50 -- /bin/sh -c ": > $f" >/dev/null 2>&1
    while [[ -n "$b64" ]]; do
      chunk="${b64:0:20000}"; b64="${b64:20000}"
      timeout 60 openshell sandbox exec -n "$sb" --timeout 50 -- /bin/sh -c "printf '%s' '$chunk' >> $f.b64" >/dev/null 2>&1
    done
    script="base64 -d $f.b64 > $f && rm -f $f.b64 && . $f && rm -f $f"
  fi
  timeout "$t" openshell sandbox exec -n "$sb" --timeout "$((t - 10 > 5 ? t - 10 : 5))" -- \
    /bin/sh -c "$pre$script" 2>&1 | grep -v '^profile: Permission' || true
}

# Write a local file into the sandbox at DEST (mode 600). Uses base64 through
# exec because `sandbox upload` creates a directory at DEST.
sandbox_put() {
  local sb="$1" src="$2" dest="$3" b64
  sandbox_owned "$sb" || die "sandbox $sb is not owned by this deployment; refusing to write to it"
  b64=$(b64 "$src")
  sbx "$sb" "mkdir -p $(dirname "$dest") && printf '%s' '$b64' | base64 -d > $dest && chmod 600 $dest && echo PUT-OK" 120 \
    | grep -q PUT-OK || die "failed to write $dest into $sb"
}

# Kernel namespace ids for isolation proofs: "hostname pid-ns net-ns mnt-ns"
sandbox_ns() {
  sbx "$1" 'printf "%s %s %s %s\n" "$(hostname)" "$(readlink /proc/self/ns/pid | tr -dc 0-9)" "$(readlink /proc/self/ns/net | tr -dc 0-9)" "$(readlink /proc/self/ns/mnt | tr -dc 0-9)"' 60 | tail -1
}
