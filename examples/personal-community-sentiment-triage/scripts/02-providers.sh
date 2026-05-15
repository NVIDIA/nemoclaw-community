#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 3: Upsert OpenShell providers for the credentials this sandbox
# needs.
#
# Providers are how secrets reach a sandbox without ever being seen by the
# agent process. A provider holds named credentials (env-var-name → value).
# Inside the sandbox, a binary references `openshell:resolve:env:VAR` and
# the L7 proxy substitutes the real value in outgoing requests at the
# header level — the agent only ever sees the placeholder.
#
# Provider names mirror what `nemoclaw onboard` would create, so this
# example produces the same provider tree:
#   compatible-endpoint           — inference (shared, no sandbox prefix)
#   <sandbox>-outlook             — Outlook (3 credentials)
#   <sandbox>-slack-bridge        — Slack bot token
#   <sandbox>-slack-app           — Slack app token
#   <sandbox>-github              — GitHub token
#
# OpenShell commands you'll see:
#   - openshell provider create / update / get / list
#   - openshell inference set    — bind a provider+model to the gateway
#
# Try after this script:
#   $ openshell provider list
#   $ openshell provider get hermes-direct-outlook

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

# At least one messaging channel must be configured — without one the
# sandbox comes up with no way for the user to reach the agent.
if [[ -z "${OUTLOOK_CLIENT_ID:-}" && -z "${SLACK_BOT_TOKEN:-}" ]]; then
  echo "No messaging channel configured — set Outlook (all five OUTLOOK_* vars) or Slack (SLACK_BOT_TOKEN + SLACK_APP_TOKEN) in $EXAMPLE_DIR/.env" >&2
  exit 1
fi

# Outlook is opt-in: leave the block blank to skip it entirely. But if the
# user has started filling it in, require *all five* — a partially-configured
# Outlook channel would silently bake a broken bridge into the image.
OUTLOOK_VARS=(OUTLOOK_TENANT_ID OUTLOOK_CLIENT_ID OUTLOOK_SESSION_UUID OUTLOOK_TARGET_MAILBOX OUTLOOK_REPLY_TO)
OUTLOOK_SET=()
OUTLOOK_MISSING=()
for v in "${OUTLOOK_VARS[@]}"; do
  if [[ -n "${!v:-}" ]]; then OUTLOOK_SET+=("$v"); else OUTLOOK_MISSING+=("$v"); fi
done
if (( ${#OUTLOOK_SET[@]} > 0 && ${#OUTLOOK_MISSING[@]} > 0 )); then
  echo "Partial Outlook configuration in $EXAMPLE_DIR/.env" >&2
  echo "  Set:     ${OUTLOOK_SET[*]}" >&2
  echo "  Missing: ${OUTLOOK_MISSING[*]}" >&2
  echo "Fill all five OUTLOOK_* vars or leave the entire block empty." >&2
  exit 1
fi

# ── Inference provider (shared, not sandbox-prefixed) ───────────────────
# Mirrors NemoClaw's REMOTE_PROVIDER_CONFIG.custom:
#   credentialEnv          = COMPATIBLE_API_KEY (host)
#   providerCredentialEnv  = OPENAI_API_KEY     (what `--credential` references)
# So we accept either name from the host shell, then store it under the
# OPENAI_API_KEY name OpenShell expects.
INFERENCE_KEY="${OPENAI_API_KEY:-${COMPATIBLE_API_KEY:-}}"
if [[ -n "$INFERENCE_KEY" ]]; then
  INFERENCE_PROVIDER="compatible-endpoint"
  INFERENCE_MODEL="${NEMOCLAW_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
  INFERENCE_BASE_URL="${NEMOCLAW_ENDPOINT_URL:-${OPENAI_BASE_URL:-https://integrate.api.nvidia.com/v1}}"
  echo "Upserting inference provider $INFERENCE_PROVIDER (model: $INFERENCE_MODEL, base: $INFERENCE_BASE_URL)"
  if openshell provider get "$INFERENCE_PROVIDER" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" OPENAI_API_KEY="$INFERENCE_KEY" \
      openshell provider update "$INFERENCE_PROVIDER" \
        --credential OPENAI_API_KEY --config "OPENAI_BASE_URL=$INFERENCE_BASE_URL"
  else
    env -i HOME="$HOME" PATH="$PATH" OPENAI_API_KEY="$INFERENCE_KEY" \
      openshell provider create --name "$INFERENCE_PROVIDER" --type openai \
        --credential OPENAI_API_KEY --config "OPENAI_BASE_URL=$INFERENCE_BASE_URL"
  fi
  echo "Setting cluster inference: provider=$INFERENCE_PROVIDER model=$INFERENCE_MODEL"
  openshell inference set --no-verify --provider "$INFERENCE_PROVIDER" --model "$INFERENCE_MODEL"
else
  echo "WARNING: neither OPENAI_API_KEY nor COMPATIBLE_API_KEY is set — skipping inference provider. The agent will have no LLM." >&2
fi

# ── Outlook provider (3 credentials on one provider name) ───────────────
if [[ -n "${OUTLOOK_CLIENT_ID:-}" ]]; then
  OUTLOOK_PROVIDER="$SANDBOX_NAME-outlook"
  echo "Upserting provider $OUTLOOK_PROVIDER (3 credentials)"
  upsert_cred "$OUTLOOK_PROVIDER" generic OUTLOOK_CLIENT_ID    "$OUTLOOK_CLIENT_ID"
  upsert_cred "$OUTLOOK_PROVIDER" generic OUTLOOK_TENANT_ID    "$OUTLOOK_TENANT_ID"
  upsert_cred "$OUTLOOK_PROVIDER" generic OUTLOOK_SESSION_UUID "$OUTLOOK_SESSION_UUID"
fi

# ── Slack providers (each on its own name, type=generic) ────────────────
if [[ -n "${SLACK_BOT_TOKEN:-}" ]]; then
  SLACK_BRIDGE_PROVIDER="$SANDBOX_NAME-slack-bridge"
  echo "Upserting provider $SLACK_BRIDGE_PROVIDER"
  upsert_cred "$SLACK_BRIDGE_PROVIDER" generic SLACK_BOT_TOKEN "$SLACK_BOT_TOKEN"
fi
if [[ -n "${SLACK_APP_TOKEN:-}" ]]; then
  SLACK_APP_PROVIDER="$SANDBOX_NAME-slack-app"
  echo "Upserting provider $SLACK_APP_PROVIDER"
  upsert_cred "$SLACK_APP_PROVIDER" generic SLACK_APP_TOKEN "$SLACK_APP_TOKEN"
fi

# ── GitHub provider ─────────────────────────────────────────────────────
if [[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]]; then
  GH_PROVIDER="$SANDBOX_NAME-github"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "Upserting provider $GH_PROVIDER (credential: GITHUB_TOKEN)"
    upsert_cred "$GH_PROVIDER" github GITHUB_TOKEN "$GITHUB_TOKEN"
  else
    echo "Upserting provider $GH_PROVIDER (credential: GH_TOKEN)"
    upsert_cred "$GH_PROVIDER" github GH_TOKEN "$GH_TOKEN"
  fi
fi

echo "Provider summary (this sandbox + shared inference):"
openshell provider list 2>&1 | grep -E "($SANDBOX_NAME|compatible-endpoint)" || true
