#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Bring up the maker/checker payment boundary end to end.
#
#   1. host services — mock payment rail (127.0.0.1:8780, HOST ONLY), the
#      release gate SUBMIT listener (127.0.0.1:8790; the sandbox reaches it only
#      via the host.openshell.internal route in policy.yaml), and the host-only
#      APPROVE listener (127.0.0.1:8791; the sandbox has no route to it)
#   2. optional local image sanity build — OpenShell builds the real image
#      itself from a staged Dockerfile in the recipe root in phase 3; this is
#      only a fast local fail-early check and is skipped without docker
#   3. sandbox — `openshell sandbox create --from <staged-Dockerfile>` with
#      policy.yaml applied WHOLE (inference routes + blackwall advisory routes +
#      release-gate SUBMIT route; no rail route, no approve route). This is what
#      the security boundary needs: verify.sh exercises the denied edge via
#      `sandbox exec` and does NOT require the Hermes agent runtime to be up.
#      The staged Dockerfile stays in the recipe root, so OpenShell uses that
#      directory as the build context and its recipe-relative COPYs resolve.
#
# Requires: python3. openshell for phase 3 (and docker only for the optional
# phase-2 sanity build); without them the host boundary still comes up and
# scripts/verify.sh --host-only can exercise it.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$DIR")"
REPO_ROOT="$(cd "$EXAMPLE_DIR/../../../../.." && pwd)"
# shellcheck source=../../../../../../scripts/example_dependencies.sh
source "$REPO_ROOT/scripts/example_dependencies.sh"
load_example_dependencies "$EXAMPLE_DIR"
require_example_harness hermes
RUN="$EXAMPLE_DIR/.run"
SANDBOX_NAME="${SANDBOX_NAME:-x402-gate-demo}"
IMAGE_TAG="${IMAGE_TAG:-x402-payment-gate-sandbox}"
STAGED_DOCKERFILE="$EXAMPLE_DIR/.Dockerfile.staged"
[[ ! -L "$STAGED_DOCKERFILE" && ( ! -e "$STAGED_DOCKERFILE" || -f "$STAGED_DOCKERFILE" ) ]] || {
  echo "Refusing unsafe staged Dockerfile path: $STAGED_DOCKERFILE" >&2
  exit 1
}
trap 'rm -f "$STAGED_DOCKERFILE"' EXIT
cp "$EXAMPLE_DIR/Dockerfile" "$STAGED_DOCKERFILE"
sed -i.bak \
  -e "s|^ARG BASE_IMAGE=.*|ARG BASE_IMAGE=$NEMOCLAW_BASE_IMAGE|" \
  -e "s|^ARG HERMES_VERSION=.*|ARG HERMES_VERSION=$HERMES_VERSION|" \
  "$STAGED_DOCKERFILE"
rm -f "${STAGED_DOCKERFILE}.bak"
mkdir -p "$RUN"

echo "== 1/3 host services (the CHECKER side) =="
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }

# Where the SUBMIT listener binds. The sandbox reaches the host over the
# OpenShell bridge (host.openshell.internal -> the openshell-docker network
# gateway), NOT host loopback -- so a gate on 127.0.0.1 is unreachable from the
# sandbox (the maker path is dead), while 0.0.0.0 would expose submission on
# every host interface (LAN included). We bind the SPECIFIC bridge interface:
# reachable by the sandbox's supervisor proxy and by the host, but not the LAN.
# The gateway recreates the openshell-docker network at startup, so its gateway
# address is discoverable before any sandbox exists. Without openshell (a
# host-only run) we fall back to loopback -- there is no sandbox to reach.
# The RAIL and APPROVE listeners ALWAYS stay on loopback: the rail's
# loopback-only bind IS the denied edge, and approve is a named human on the
# host. Only the least-privileged SUBMIT listener is exposed to the bridge.
GATE_BIND="127.0.0.1"
if command -v openshell >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
  bridge="$(docker network inspect openshell-docker \
    -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
  if [ -n "$bridge" ]; then
    GATE_BIND="$bridge"
  else
    echo "  WARN: openshell-docker bridge not found (is the gateway running?)." >&2
    echo "  Binding the SUBMIT listener to loopback; the in-sandbox maker path" >&2
    echo "  will NOT work until the gate is bound to the bridge. Start the" >&2
    echo "  openshell gateway, then re-run bring-up." >&2
  fi
fi
GATE_URL="http://$GATE_BIND:8790"

# Own our processes: only reuse a service THIS lifecycle started (tracked by
# pid file) and still alive. Never silently adopt an arbitrary process that
# merely answers /healthz on the port -- that could be a prior checkout or an
# unrelated service, and fresh verification would then exercise stale code.
# If the port is held by something we do not own, fail with an actionable
# error rather than reusing it.
start_service() { # start_service <name> <script> <port> <bind>
  local name="$1" script="$2" port="$3" bind="$4"
  local pidf="$RUN/$name.pid"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then
    echo "  $name: reusing our running instance (pid $(cat "$pidf"))"
    return 0
  fi
  if curl -sS -m 2 "http://$bind:$port/healthz" >/dev/null 2>&1; then
    echo "  ERROR: $bind:$port is already serving, but not a process this" >&2
    echo "         lifecycle owns (no live pid file). Stop it, or run" >&2
    echo "         scripts/tear-down.sh, before bring-up. Refusing to reuse" >&2
    echo "         an unknown process (it may run stale code)." >&2
    exit 1
  fi
  # RELEASE_GATE_BIND is read by release_gate.py for the SUBMIT listener;
  # mock_rail.py ignores it (the rail is loopback-only by design). We `exec` the
  # backgrounded subshell straight into python3, so $! is python3's OWN pid --
  # NOT the wrapping subshell's. tear-down.sh kills by this pid, so it must be
  # the real one (capturing the subshell pid leaves the service running).
  ( cd "$EXAMPLE_DIR/host" \
      && exec env RELEASE_GATE_BIND="$bind" nohup python3 "$script" ) \
      > "$RUN/$name.log" 2>&1 &
  echo $! > "$pidf"
  echo "  $name: started (pid $(cat "$pidf"))"
}
start_service rail mock_rail.py 8780 127.0.0.1
start_service gate release_gate.py 8790 "$GATE_BIND"
# Record the host-reachable gate URL so scripts/verify.sh targets the same
# address the SUBMIT listener actually bound (loopback or bridge).
printf '%s\n' "$GATE_URL" > "$RUN/gate.url"
sleep 1
curl -sS -m 5 http://127.0.0.1:8780/healthz >/dev/null && echo "  mock rail: healthy (host-only; NO sandbox route by design)"
curl -sS -m 5 "$GATE_URL/healthz" >/dev/null && echo "  release gate: healthy (SUBMIT on $GATE_BIND:8790; approve host-only on 8791)"

echo
echo "== 2/3 optional local image sanity build =="
# OpenShell builds the sandbox image itself from the staged Dockerfile via the
# `--from` flag in phase 3 (see below) -- there is NO separate `--image`
# step. This phase is only a fast, local fail-early check that the Dockerfile
# builds; it is entirely optional and skipped when docker is absent. Build
# context is the recipe root, so the COPY paths resolve.
if command -v docker >/dev/null 2>&1; then
  if docker build -t "$IMAGE_TAG" -f "$STAGED_DOCKERFILE" "$EXAMPLE_DIR"; then
    echo "  Dockerfile builds cleanly ($IMAGE_TAG). OpenShell will build its own"
    echo "  copy from --from in phase 3."
  else
    echo "  WARN: local docker build failed. This is only a pre-flight sanity"
    echo "  check; OpenShell still builds from --from in phase 3."
  fi
else
  echo "  skipped: docker not available (only used for the optional local"
  echo "  sanity build; OpenShell builds from --from in phase 3)."
fi

echo
echo "== 3/3 sandbox ($SANDBOX_NAME) =="
# What this phase stands up is the security boundary: a sandbox with
# policy.yaml applied. The denied-edge and in-sandbox maker checks in
# verify.sh run via `openshell sandbox exec` (curl/python3 straight inside the
# sandbox) and therefore do NOT need the Hermes agent runtime to be running --
# they need only this created sandbox + its policy. Running the interactive
# Hermes MAKER agent (the SKILL.md UX) additionally needs a full NemoClaw
# Relay+Hermes image and `nemoclaw-start`; that is an operator step layered on
# top, not part of the boundary this recipe verifies.
if ! command -v openshell >/dev/null 2>&1; then
  echo "  skipped: openshell not in PATH. Run scripts/verify.sh now to exercise"
  echo "  the host boundary; re-run bring-up where openshell is available for"
  echo "  the full sandbox + denied-edge test."
  exit 0
fi
require_example_dependency_version \
  "OpenShell" "$OPENSHELL_VERSION" openshell --version
# A sandbox with this name may have been built from an OLDER checkout, and
# reusing it (only re-applying policy) would run stale Dockerfile/skill/client
# content -- which verify.sh, exercising the sandbox over curl/exec, cannot
# detect. So we ALWAYS rebuild from THIS checkout: delete any existing sandbox
# of this name, then create it fresh.
if openshell sandbox list 2>/dev/null | grep -qE "^\s*$SANDBOX_NAME\s"; then
  echo "  sandbox '$SANDBOX_NAME' already exists -- deleting it so we rebuild from"
  echo "  this checkout (reusing it could run a stale Dockerfile/skill/client)."
  openshell sandbox delete "$SANDBOX_NAME" </dev/null >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    openshell sandbox list 2>/dev/null | grep -qE "^\s*$SANDBOX_NAME\s" || break
    sleep 1
  done
fi
# OpenShell builds the image from a staged Dockerfile in the recipe root. That
# keeps the recipe root as the build context so its COPY paths resolve while
# letting dependencies.toml select the immutable base image.
#
# `create` provisions the sandbox and then tries to attach an interactive
# session; run from a script (no controlling TTY) that attach fails with an
# "os error 2" and a NON-ZERO exit -- even though the sandbox is created and
# goes on to reach Ready. So we must NOT let that exit abort bring-up under
# `set -e`: tolerate it and treat the Ready-poll below as the source of truth.
# A genuine build/policy failure instead shows up as an Error phase, which the
# poll detects and reports immediately.
openshell sandbox create \
  --from "$STAGED_DOCKERFILE" \
  --name "$SANDBOX_NAME" \
  --policy "$EXAMPLE_DIR/policy.yaml" </dev/null || true
echo "  waiting for sandbox to reach Ready..."
ready=0
for _ in $(seq 1 240); do
  phase="$(openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" || true)"
  if printf '%s' "$phase" | grep -qi ready; then ready=1; break; fi
  if printf '%s' "$phase" | grep -qi error; then
    echo "  ERROR: sandbox '$SANDBOX_NAME' entered an Error phase:" >&2
    printf '         %s\n' "$phase" >&2
    exit 1
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "  ERROR: sandbox did not reach Ready in ~8 min. Inspect with" >&2
  echo "         'openshell sandbox list'." >&2
  exit 1
fi
echo "  sandbox Ready"
openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$SANDBOX_NAME"
# Prove the sandbox can actually execute the in-sandbox test tooling before
# handing off to verify.sh (which relies on `sandbox exec` curl/python3).
if openshell sandbox exec --name "$SANDBOX_NAME" -- python3 --version >/dev/null 2>&1; then
  echo "  sandbox exec works (python3 present) -- ready for scripts/verify.sh"
else
  echo "  WARN: 'sandbox exec python3' failed; verify.sh stage 3 needs in-sandbox"
  echo "  python3/curl. Check the image's binary allowlist and base tooling." >&2
fi
echo
echo "bring-up complete. Next: scripts/verify.sh"
