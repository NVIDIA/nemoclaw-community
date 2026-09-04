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
sandbox_create() {
  local sb="$1" pol="$2" i phase
  if sandbox_exists "$sb"; then
    dim "sandbox $sb exists ($(sandbox_phase "$sb"))"
  else
    timeout 180 openshell sandbox create --name "$sb" --from "$(image_tag)" \
      --policy "$pol" --memory "$SANDBOX_MEMORY" --cpu "$SANDBOX_CPU" >/dev/null 2>&1 || true
  fi
  for ((i = 0; i < 30; i++)); do
    phase=$(sandbox_phase "$sb")
    [[ "$phase" == Ready ]] && { ok "sandbox $sb Ready"; return 0; }
    [[ "$phase" == Error ]] && die "sandbox $sb entered Error; see: docker logs \$(docker ps -a --filter name=$sb -q | head -1)"
    sleep 6
  done
  die "sandbox $sb not Ready after 3 min (phase: ${phase:-none})"
}

sandbox_delete() {
  local sb="$1"
  sandbox_exists "$sb" || return 0
  timeout 180 openshell sandbox delete "$sb" >/dev/null 2>&1 || true
  local i
  for ((i = 0; i < 20; i++)); do
    sandbox_exists "$sb" || { ok "sandbox $sb deleted"; return 0; }
    sleep 3
  done
  warn "sandbox $sb still listed after delete"
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
  b64=$(b64 "$src")
  sbx "$sb" "mkdir -p $(dirname "$dest") && printf '%s' '$b64' | base64 -d > $dest && chmod 600 $dest && echo PUT-OK" 120 \
    | grep -q PUT-OK || die "failed to write $dest into $sb"
}

# Kernel namespace ids for isolation proofs: "hostname pid-ns net-ns mnt-ns"
sandbox_ns() {
  sbx "$1" 'printf "%s %s %s %s\n" "$(hostname)" "$(readlink /proc/self/ns/pid | tr -dc 0-9)" "$(readlink /proc/self/ns/net | tr -dc 0-9)" "$(readlink /proc/self/ns/mnt | tr -dc 0-9)"' 60 | tail -1
}
