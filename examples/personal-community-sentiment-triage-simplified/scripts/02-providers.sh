#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 3: Upsert OpenShell providers for the credentials this sandbox
# needs.
#
# Required:
#   compatible-endpoint           — inference provider
#   <sandbox>-slack-bridge        — Slack bot token
#   <sandbox>-slack-app           — Slack app token
#   <sandbox>-tavily              — Tavily API key
#
#   <sandbox>-github              — GitHub token for gh CLI/API access

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env

for v in SLACK_BOT_TOKEN SLACK_APP_TOKEN TAVILY_API_KEY; do
  [[ -n "${!v:-}" ]] || { echo "Missing $v — populate $EXAMPLE_DIR/.env" >&2; exit 1; }
done
[[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]] || {
  echo "Missing GITHUB_TOKEN or GH_TOKEN — populate $EXAMPLE_DIR/.env" >&2
  exit 1
}

# ── Inference provider (shared, not sandbox-prefixed) ───────────────────
INFERENCE_KEY="${OPENAI_API_KEY:-${COMPATIBLE_API_KEY:-}}"
[[ -n "$INFERENCE_KEY" ]] || {
  echo "Missing COMPATIBLE_API_KEY or OPENAI_API_KEY — populate $EXAMPLE_DIR/.env" >&2
  exit 1
}

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

# ── Slack providers ─────────────────────────────────────────────────────
SLACK_BRIDGE_PROVIDER="$SANDBOX_NAME-slack-bridge"
echo "Upserting provider $SLACK_BRIDGE_PROVIDER"
upsert_cred "$SLACK_BRIDGE_PROVIDER" generic SLACK_BOT_TOKEN "$SLACK_BOT_TOKEN"

SLACK_APP_PROVIDER="$SANDBOX_NAME-slack-app"
echo "Upserting provider $SLACK_APP_PROVIDER"
upsert_cred "$SLACK_APP_PROVIDER" generic SLACK_APP_TOKEN "$SLACK_APP_TOKEN"

# ── Tavily provider ────────────────────────────────────────────────────
TAVILY_PROVIDER="$SANDBOX_NAME-tavily"
echo "Upserting provider $TAVILY_PROVIDER"
upsert_cred "$TAVILY_PROVIDER" generic TAVILY_API_KEY "$TAVILY_API_KEY"

# ── GitHub provider ─────────────────────────────────────────────────────
GH_PROVIDER="$SANDBOX_NAME-github"
GH_VALUE="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
echo "Upserting provider $GH_PROVIDER (credential: GITHUB_TOKEN)"
upsert_cred "$GH_PROVIDER" github GITHUB_TOKEN "$GH_VALUE"

echo "Provider summary (this sandbox + shared inference):"
openshell provider list 2>&1 | grep -E "($SANDBOX_NAME|compatible-endpoint)" || true
