#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 3 of 3: Build the sandbox image and create the sandbox.
#
# `openshell sandbox create --from <Dockerfile>` builds the image — there's
# no --build-arg passthrough, so we sed-patch a staged Dockerfile copy with
# the per-run values before handing it off. After create, we re-apply policy
# via `openshell policy set --wait` (NemoClaw's two-stage pattern: create
# with base policy, then activate network policies).

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_messaging_config
command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

STAGED_DOCKERFILE="$EXAMPLE_DIR/.Dockerfile.staged"
STAGED_POLICY="$EXAMPLE_DIR/.policy.staged.yaml"
trap 'rm -f "$STAGED_DOCKERFILE" "$STAGED_POLICY"' EXIT

# Build base64-JSON blobs for the Hermes config generator (channels + allowed IDs).
mapfile -t _B64 < <("$DIR/lib/build-channels.py")
CHANNELS_B64="${_B64[0]}"
ALLOWED_IDS_B64="${_B64[1]}"
echo "Channels:    $(printf '%s' "$CHANNELS_B64" | base64 -d)"
echo "Allowed IDs: $(printf '%s' "$ALLOWED_IDS_B64" | base64 -d)"

ALLOWED_SENDERS="${OUTLOOK_ALLOWED_SENDERS:-}"
SOURCE_ETL_HOST="${SOURCE_ETL_API_HOST:-host.openshell.internal}"
SOURCE_ETL_PORT="${SOURCE_ETL_API_PORT:-3100}"
GITHUB_READONLY_REPO="${GITHUB_READONLY_REPO:-NVIDIA/OpenShell}"
if [[ ! "$GITHUB_READONLY_REPO" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid GITHUB_READONLY_REPO '$GITHUB_READONLY_REPO' — expected owner/repo" >&2
  exit 1
fi
echo "GitHub read-only repo scope: $GITHUB_READONLY_REPO"

# ── Stage the Dockerfile and patch ARG defaults ────────────────────────
# Build args go through sed substitution because `openshell sandbox create
# --from <Dockerfile>` doesn't expose --build-arg passthrough. Values must
# not contain `|` (the sed delimiter).
declare -A DOCKERFILE_ARGS=(
  [NEMOCLAW_MESSAGING_CHANNELS_B64]="$CHANNELS_B64"
  [NEMOCLAW_MESSAGING_ALLOWED_IDS_B64]="$ALLOWED_IDS_B64"
  [OUTLOOK_TARGET_MAILBOX]="${OUTLOOK_TARGET_MAILBOX:-}"
  [OUTLOOK_REPLY_TO]="${OUTLOOK_REPLY_TO:-}"
  [OUTLOOK_ALLOWED_SENDERS]="$ALLOWED_SENDERS"
  [GITHUB_READONLY_REPO]="$GITHUB_READONLY_REPO"
  [SOURCE_ETL_API_HOST]="$SOURCE_ETL_HOST"
  [SOURCE_ETL_API_PORT]="$SOURCE_ETL_PORT"
  [NEMOCLAW_BUILD_ID]="$(date +%s)"
)
# Optional patches — leave the Dockerfile default in place if unset.
[[ -n "${NEMOCLAW_MODEL:-}" ]] && DOCKERFILE_ARGS[NEMOCLAW_MODEL]="$NEMOCLAW_MODEL"
if [[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
  echo "Phoenix endpoint: $PHOENIX_COLLECTOR_ENDPOINT — enabling OpenInference egress"
  DOCKERFILE_ARGS[PHOENIX_COLLECTOR_ENDPOINT]="$PHOENIX_COLLECTOR_ENDPOINT"
fi
if [[ -n "${PHOENIX_PROJECT_NAME:-}" ]]; then
  echo "Phoenix project: $PHOENIX_PROJECT_NAME"
  DOCKERFILE_ARGS[PHOENIX_PROJECT_NAME]="$PHOENIX_PROJECT_NAME"
fi
# ATIF S3 export — bake the bucket + key_prefix into the relay's plugins.toml
# at sandbox-create time (the SDK reads them from there). When the bucket is
# unset (or BACKEND=local), no storage block is emitted; start.sh's
# ATIF_STORAGE_ENABLED probe (which greps plugins.toml for the storage block)
# returns 0, the bridge stays down, AWS_* exports are skipped, and ATIF
# writes go to the sandbox's local /tmp/atif/ instead.
if atif_remote_enabled; then
  echo "ATIF S3 export: backend=$ATIF_STORAGE_BACKEND bucket=${ATIF_STORAGE_BUCKET:-} prefix=${ATIF_STORAGE_KEY_PREFIX:-hermes/}"
  DOCKERFILE_ARGS[ATIF_STORAGE_BACKEND]="$ATIF_STORAGE_BACKEND"
  DOCKERFILE_ARGS[ATIF_STORAGE_BUCKET]="${ATIF_STORAGE_BUCKET:-}"
  DOCKERFILE_ARGS[ATIF_STORAGE_KEY_PREFIX]="${ATIF_STORAGE_KEY_PREFIX:-hermes/}"
  [[ -n "${ATIF_S3_REGION:-}" ]] && DOCKERFILE_ARGS[ATIF_S3_REGION]="$ATIF_S3_REGION"
fi

cp "$EXAMPLE_DIR/agents/hermes/Dockerfile" "$STAGED_DOCKERFILE"
for arg in "${!DOCKERFILE_ARGS[@]}"; do
  value="${DOCKERFILE_ARGS[$arg]}"
  sed -i -e "s|^ARG ${arg}=.*|ARG ${arg}=${value}|" "$STAGED_DOCKERFILE"
done

# ── Stage policy and patch per-run repo scope ───────────────────────────
cp "$EXAMPLE_DIR/policy.yaml" "$STAGED_POLICY"
sed -i \
  -e "s|__GITHUB_READONLY_REPO__|$GITHUB_READONLY_REPO|g" \
  "$STAGED_POLICY"

# ── Build provider flags from what 02-providers.sh actually created ────
PROVIDER_FLAGS=()
# Inference (`compatible-endpoint`) is consumed via `openshell inference set`
# routing (inference.local), not via direct sandbox attachment.
[[ -n "${OUTLOOK_CLIENT_ID:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-outlook")
[[ -n "${SLACK_BOT_TOKEN:-}" || -n "${SLACK_APP_TOKEN:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-slack")
[[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]] && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-github")
atif_remote_enabled && PROVIDER_FLAGS+=(--provider "$SANDBOX_NAME-atif-export-relay")

# ── Create the sandbox ─────────────────────────────────────────────────
# `openshell sandbox create` proxies the sandbox's stdout to the local
# terminal until the initial command exits — our command is a long-running
# daemon, so we spawn create in the background, poll for ready, then signal
# the openshell process group to detach. The sandbox itself runs on the
# gateway and survives the local kill.
#
# `setsid` + pgrp-kill is a workaround for an OpenShell ≤ 0.0.36 UX bug
# where the `ssh` subprocess streaming sandbox stdout wasn't cleaned up on
# SIGTERM. If `pgrep -af openshell | grep -v grep` is empty after this
# script returns on 0.0.50+, the bug is fixed and the `setsid` wrapper +
# SIGKILL backstop below can be simplified to plain `&` + `kill -TERM $PID`.
echo "Creating sandbox $SANDBOX_NAME (OpenShell will build the image)…"
setsid openshell sandbox create \
  --from "$STAGED_DOCKERFILE" \
  --name "$SANDBOX_NAME" \
  --policy "$STAGED_POLICY" \
  "${PROVIDER_FLAGS[@]}" \
  -- env \
    OUTLOOK_TARGET_MAILBOX="${OUTLOOK_TARGET_MAILBOX:-}" \
    OUTLOOK_REPLY_TO="${OUTLOOK_REPLY_TO:-}" \
    OUTLOOK_ALLOWED_SENDERS="$ALLOWED_SENDERS" \
    GITHUB_READONLY_REPO="$GITHUB_READONLY_REPO" \
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
# Without this, network rules from the staged policy may not be activated
# even though they were passed at create time. Symptom: L7 proxy denies
# sandbox outbound requests with `[policy:<provider>]` despite a matching
# rule (e.g. MS Graph for outlook, api.github.com for github, the relay
# endpoint for atif).
echo "Re-applying policy via 'openshell policy set --wait' (stage 2)"
openshell policy set --policy "$STAGED_POLICY" --wait "$SANDBOX_NAME"

echo "Sandbox $SANDBOX_NAME is ready."
