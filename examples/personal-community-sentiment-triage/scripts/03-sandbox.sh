#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 3 of 3: Build the sandbox image and create the sandbox.
#
# OpenShell builds the image from a Dockerfile (`openshell sandbox create
# --from <Dockerfile>`). We can't pre-build with `docker build` and then
# pass a local-only tag — `--from` only accepts a Dockerfile path, a build
# directory, or a registry-hosted image. OpenShell also doesn't expose a
# `--build-arg` passthrough, so this script sed-patches a staged copy of
# the Dockerfile to bake in the per-run values (mailbox, channels, Phoenix
# endpoint, etc.) before handing it to OpenShell.
#
# After create, this script re-applies the policy via `openshell policy
# set --wait`. That's the second stage of NemoClaw's two-stage policy
# pattern — create with a base policy, then activate the network policies.
# Without this, certain rules (notably the outlook token-manager allow)
# fail to take effect even though the YAML was loaded at create time.
#
# OpenShell commands you'll see:
#   - openshell sandbox create --from <Dockerfile> --policy <yaml> --provider <p> -- env … cmd
#   - openshell sandbox list / logs / connect
#   - openshell policy set --wait <sandbox>
#
# Try after this script:
#   $ openshell sandbox list
#   $ openshell sandbox exec hermes-direct curl -sf http://localhost:8642/health
#   $ openshell sandbox connect hermes-direct

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

# Required input — fail loudly rather than building an unauthable sandbox.
for v in OUTLOOK_CLIENT_ID OUTLOOK_TENANT_ID OUTLOOK_SESSION_UUID \
         OUTLOOK_TARGET_MAILBOX OUTLOOK_REPLY_TO; do
  [[ -n "${!v:-}" ]] || { echo "Missing $v — populate $EXAMPLE_DIR/.env" >&2; exit 1; }
done
command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

STAGED_DOCKERFILE="$EXAMPLE_DIR/.Dockerfile.staged"
trap 'rm -f "$STAGED_DOCKERFILE"' EXIT

# ── Build CHANNELS_B64 and ALLOWED_IDS_B64 ─────────────────────────────
# These two base64-JSON blobs tell the Hermes config generator which
# messaging platforms are enabled and per-platform user allowlists. The
# Dockerfile bakes them in as ARGs, then generate-config.ts decodes them
# at image build time into SLACK_ALLOWED_USERS / TELEGRAM_ALLOWED_USERS
# config keys. Same shape as `nemoclaw onboard` produces — see
# src/lib/onboard.ts:1568-1572.
read -r -d '' _BUILD_B64_PY <<'PY' || true
import os, json, base64
channels = []
if os.environ.get("OUTLOOK_CLIENT_ID"):  channels.append("outlook")
if os.environ.get("SLACK_BOT_TOKEN"):    channels.append("slack")
if os.environ.get("TELEGRAM_BOT_TOKEN"): channels.append("telegram")
if os.environ.get("DISCORD_BOT_TOKEN"):  channels.append("discord")
allowed = {}
for ch, env in [("slack", "SLACK_ALLOWED_IDS"), ("telegram", "TELEGRAM_ALLOWED_IDS")]:
    v = (os.environ.get(env) or "").strip()
    if v:
        allowed[ch] = [s.strip() for s in v.split(",") if s.strip()]
print(base64.b64encode(json.dumps(channels).encode()).decode())
print(base64.b64encode(json.dumps(allowed).encode()).decode())
PY
mapfile -t _B64 < <(python3 -c "$_BUILD_B64_PY")
CHANNELS_B64="${_B64[0]}"
ALLOWED_IDS_B64="${_B64[1]}"
echo "Channels:    $(printf '%s' "$CHANNELS_B64" | base64 -d)"
echo "Allowed IDs: $(printf '%s' "$ALLOWED_IDS_B64" | base64 -d)"

ALLOWED_SENDERS="${OUTLOOK_ALLOWED_SENDERS:-}"
TM_HOST="$(detect_token_manager_host)"
echo "Resolved TOKEN_MANAGER_HOST → $TM_HOST"

# ── Stage the Dockerfile and patch ARG defaults ────────────────────────
cp "$EXAMPLE_DIR/agents/hermes/Dockerfile" "$STAGED_DOCKERFILE"
sed -i \
  -e "s|^ARG NEMOCLAW_MESSAGING_CHANNELS_B64=.*|ARG NEMOCLAW_MESSAGING_CHANNELS_B64=$CHANNELS_B64|" \
  -e "s|^ARG NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=.*|ARG NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=$ALLOWED_IDS_B64|" \
  -e "s|^ARG OUTLOOK_TARGET_MAILBOX=.*|ARG OUTLOOK_TARGET_MAILBOX=$OUTLOOK_TARGET_MAILBOX|" \
  -e "s|^ARG OUTLOOK_REPLY_TO=.*|ARG OUTLOOK_REPLY_TO=$OUTLOOK_REPLY_TO|" \
  -e "s|^ARG OUTLOOK_ALLOWED_SENDERS=.*|ARG OUTLOOK_ALLOWED_SENDERS=$ALLOWED_SENDERS|" \
  -e "s|^ARG TOKEN_MANAGER_HOST=.*|ARG TOKEN_MANAGER_HOST=$TM_HOST|" \
  -e "s|^ARG NEMOCLAW_BUILD_ID=.*|ARG NEMOCLAW_BUILD_ID=$(date +%s)|" \
  "$STAGED_DOCKERFILE"

# Phoenix telemetry — flip ENABLE_NEMO_FLOW=1 so the Dockerfile installs
# nemo-flow==0.1.0 from PyPI and applies the Hermes integration patch.
if [[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
  echo "Phoenix endpoint: $PHOENIX_COLLECTOR_ENDPOINT — enabling NeMo-Flow telemetry"
  sed -i \
    -e "s|^ARG ENABLE_NEMO_FLOW=.*|ARG ENABLE_NEMO_FLOW=1|" \
    -e "s|^ARG PHOENIX_COLLECTOR_ENDPOINT=.*|ARG PHOENIX_COLLECTOR_ENDPOINT=$PHOENIX_COLLECTOR_ENDPOINT|" \
    "$STAGED_DOCKERFILE"
fi

# ── Build provider flags from what 02-providers.sh actually created ────
PROVIDER_FLAGS=(--provider "$SANDBOX_NAME-outlook")
[[ -n "${SLACK_BOT_TOKEN:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-slack-bridge")
[[ -n "${SLACK_APP_TOKEN:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-slack-app")
[[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-github")

# ── Create the sandbox ─────────────────────────────────────────────────
# `openshell sandbox create` proxies the running sandbox's stdout to the
# local terminal until the initial command exits. Our initial command is a
# long-running daemon, so the call would block forever. The fix mirrors
# NemoClaw's streamSandboxCreate() in src/lib/sandbox-create-stream.ts:
# spawn create in the background, poll for ready, then SIGTERM the local
# proxy as soon as the sandbox reports ready. The sandbox runs on the
# gateway and survives the local proxy being killed.
#
# `setsid` puts openshell in its own session/process-group (PGID == its PID).
# openshell spawns an `ssh` subprocess to stream sandbox stdout, and that
# ssh inherits openshell's PGID. On SIGTERM, openshell exits but does NOT
# clean up its ssh child (UX bug in openshell 0.0.36); the orphaned ssh
# would otherwise keep streaming sandbox logs to the user's terminal.
# By signalling the negative PID (`kill -- -$PID`) we hit the whole pgrp,
# including the orphan ssh, so the terminal goes silent on detach.
echo "Creating sandbox $SANDBOX_NAME (OpenShell will build the image)…"
setsid openshell sandbox create \
  --from "$STAGED_DOCKERFILE" \
  --name "$SANDBOX_NAME" \
  --policy "$EXAMPLE_DIR/policy.yaml" \
  "${PROVIDER_FLAGS[@]}" \
  -- env \
    OUTLOOK_TARGET_MAILBOX="$OUTLOOK_TARGET_MAILBOX" \
    OUTLOOK_REPLY_TO="$OUTLOOK_REPLY_TO" \
    OUTLOOK_ALLOWED_SENDERS="$ALLOWED_SENDERS" \
    TOKEN_MANAGER_HOST="$TM_HOST" \
    NEMOCLAW_MESSAGING_CHANNELS_B64="$CHANNELS_B64" \
    CHAT_UI_URL="http://127.0.0.1:8642" \
    PHOENIX_COLLECTOR_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-}" \
  nemoclaw-start </dev/null &
CREATE_PID=$!

# ── Wait for ready ─────────────────────────────────────────────────────
# 180 × 2s = 6 min, generous enough for a cold-cache build. If the create
# process dies before ready, bail with its exit status rather than hanging.
echo "Waiting for sandbox $SANDBOX_NAME to reach ready…"
READY=0
for _ in {1..180}; do
  if openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" | grep -qi ready; then
    READY=1
    break
  fi
  if ! kill -0 "$CREATE_PID" 2>/dev/null; then
    wait "$CREATE_PID" 2>/dev/null
    echo "openshell sandbox create exited before sandbox reached ready" >&2
    exit 1
  fi
  sleep 2
done

# Detach: SIGTERM the whole openshell process group (negative PID via
# `kill -- -$PID`). This catches both the openshell CLI itself and the
# `ssh` subprocess it spawns to stream sandbox stdout — without the pgrp
# kill, openshell exits but doesn't clean up its ssh child, leaving an
# orphan process attached to the user's terminal. SIGKILL fallback after
# 2s caps the worst case. `wait` on the openshell PID confirms it's gone
# before the script returns, so the terminal is silent on prompt return.
# The sandbox itself runs on the gateway and survives the local kill.
kill -TERM -- -"$CREATE_PID" 2>/dev/null || true
( sleep 2; kill -KILL -- -"$CREATE_PID" 2>/dev/null ) &
SIGKILL_BG_PID=$!
wait "$CREATE_PID" 2>/dev/null || true
kill "$SIGKILL_BG_PID" 2>/dev/null || true
wait "$SIGKILL_BG_PID" 2>/dev/null || true

if [[ "$READY" != "1" ]]; then
  echo "Sandbox did not reach ready in 360s — check 'openshell sandbox logs $SANDBOX_NAME'" >&2
  exit 1
fi
echo "  Sandbox reported ready; detached local create stream."

# ── Re-apply policy (matches nemoclaw onboard's two-stage flow) ────────
# Without this, network rules from policy.yaml may not be activated even
# though they were passed at create time. Symptom: L7 proxy denies outlook
# token-manager requests with `[policy:outlook]` despite a matching rule.
echo "Re-applying policy via 'openshell policy set --wait' (stage 2)"
openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$SANDBOX_NAME"

echo "Sandbox $SANDBOX_NAME is ready."
