#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 2 of 3: Import v2 provider profiles and upsert this sandbox's providers.
# Outlook providers run an interactive Microsoft device-code login the first
# time (refresh token cached under .bootstrap/cache/). Set OUTLOOK_FORCE_LOGIN=1
# to re-login.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_messaging_config

# Confirm provider v2 is enabled (set once globally via `openshell settings set`).
if ! openshell settings get --global 2>/dev/null | grep -qE "providers_v2_enabled\s*=\s*true"; then
  echo "providers_v2_enabled is not set at gateway-global scope." >&2
  echo "Run: openshell settings set --global --key providers_v2_enabled --value true --yes" >&2
  exit 1
fi

echo "Importing v2 provider profiles from $EXAMPLE_DIR/providers/"
# Delete-then-import so YAML edits land on re-run. `provider profile import`
# rejects existing IDs rather than upserting; ignoring delete errors covers
# first-run (nothing to delete) and any pre-existing custom profiles.
for profile_id in nemoclaw-compatible-endpoint nemoclaw-outlook-email nemoclaw-slack nemoclaw-github \
                  nemoclaw-slack-bridge nemoclaw-slack-app; do
  openshell provider profile delete "$profile_id" >/dev/null 2>&1 || true
done
openshell provider profile import --from "$EXAMPLE_DIR/providers/"

# ── Inference provider ──────────────────────────────────────────────────
INFERENCE_KEY="${OPENAI_API_KEY:-${COMPATIBLE_API_KEY:-}}"
if [[ -n "$INFERENCE_KEY" ]]; then
  INFERENCE_PROVIDER="compatible-endpoint"
  INFERENCE_BASE_URL="${NEMOCLAW_ENDPOINT_URL:-${OPENAI_BASE_URL:-https://integrate.api.nvidia.com/v1}}"
  echo "Upserting inference provider $INFERENCE_PROVIDER (base: $INFERENCE_BASE_URL)"
  # The agent calls $INFERENCE_BASE_URL directly (baked into the image via
  # 03-sandbox.sh's NEMOCLAW_INFERENCE_BASE_URL ARG patch); the L7 proxy
  # substitutes the OPENAI_API_KEY placeholder on egress. No `inference set`
  # routing layer — same pattern as the Outlook bridge.
  upsert_cred "$INFERENCE_PROVIDER" nemoclaw-compatible-endpoint OPENAI_API_KEY "$INFERENCE_KEY"
else
  echo "WARNING: neither OPENAI_API_KEY nor COMPATIBLE_API_KEY is set — skipping inference provider. The agent will have no LLM." >&2
fi

# ── Outlook provider with gateway-managed OAuth refresh ─────────────────
if [[ -n "${OUTLOOK_CLIENT_ID:-}" ]]; then
  OUTLOOK_PROVIDER="$SANDBOX_NAME-outlook"
  OUTLOOK_LOGIN_CACHE="${OUTLOOK_LOGIN_CACHE:-$EXAMPLE_DIR/.bootstrap/cache/ms-graph-token.json}"
  mkdir -p "$(dirname "$OUTLOOK_LOGIN_CACHE")"

  if [[ -f "$OUTLOOK_LOGIN_CACHE" && "${OUTLOOK_FORCE_LOGIN:-}" != "1" ]]; then
    echo "Reusing cached Microsoft refresh token at $OUTLOOK_LOGIN_CACHE (OUTLOOK_FORCE_LOGIN=1 to redo)"
    login_json="$(cat "$OUTLOOK_LOGIN_CACHE")"
  else
    login_hint_args=()
    [[ -n "${OUTLOOK_TARGET_MAILBOX:-}" ]] && login_hint_args+=(--login-hint "$OUTLOOK_TARGET_MAILBOX")
    login_json="$(python3 "$DIR/login-ms-graph.py" \
      --tenant-id "$OUTLOOK_TENANT_ID" \
      --client-id "$OUTLOOK_CLIENT_ID" \
      "${login_hint_args[@]}")"
    umask 077
    printf '%s\n' "$login_json" > "$OUTLOOK_LOGIN_CACHE"
  fi

  refresh_token="$(printf '%s' "$login_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["refresh_token"])')"
  expires_at_ms="$(printf '%s' "$login_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["expires_at_ms"])')"

  echo "Upserting provider $OUTLOOK_PROVIDER (OAuth refresh-token strategy)"
  if ! openshell provider get "$OUTLOOK_PROVIDER" >/dev/null 2>&1; then
    openshell provider create --name "$OUTLOOK_PROVIDER" --type nemoclaw-outlook-email \
      --credential "MS_GRAPH_ACCESS_TOKEN=bootstrap-placeholder"
  fi

  openshell provider refresh configure "$OUTLOOK_PROVIDER" \
    --credential-key MS_GRAPH_ACCESS_TOKEN \
    --strategy oauth2-refresh-token \
    --material "tenant_id=$OUTLOOK_TENANT_ID" \
    --material "client_id=$OUTLOOK_CLIENT_ID" \
    --material "refresh_token=$refresh_token" \
    --secret-material-key refresh_token \
    --credential-expires-at "$expires_at_ms"

  openshell provider refresh rotate "$OUTLOOK_PROVIDER" --credential-key MS_GRAPH_ACCESS_TOKEN
fi

# ── Slack provider (bot token + app token in one v2 provider) ──────────
if [[ -n "${SLACK_BOT_TOKEN:-}" || -n "${SLACK_APP_TOKEN:-}" ]]; then
  SLACK_PROVIDER="$SANDBOX_NAME-slack"
  SLACK_TYPE="nemoclaw-slack"
  echo "Upserting provider $SLACK_PROVIDER (credentials: SLACK_BOT_TOKEN + SLACK_APP_TOKEN)"
  # Recreate if existing provider has the wrong type (legacy slack-bridge/slack-app
  # records from before the merge).
  if openshell provider get "$SLACK_PROVIDER" >/dev/null 2>&1 \
       && ! provider_type_matches "$SLACK_PROVIDER" "$SLACK_TYPE"; then
    echo "  $SLACK_PROVIDER exists with wrong type; recreating as $SLACK_TYPE"
    openshell provider delete "$SLACK_PROVIDER" >/dev/null
  fi
  if openshell provider get "$SLACK_PROVIDER" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" \
      SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}" SLACK_APP_TOKEN="${SLACK_APP_TOKEN:-}" \
      openshell provider update "$SLACK_PROVIDER" \
        --credential SLACK_BOT_TOKEN --credential SLACK_APP_TOKEN
  else
    env -i HOME="$HOME" PATH="$PATH" \
      SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}" SLACK_APP_TOKEN="${SLACK_APP_TOKEN:-}" \
      openshell provider create --name "$SLACK_PROVIDER" --type "$SLACK_TYPE" \
        --credential SLACK_BOT_TOKEN --credential SLACK_APP_TOKEN
  fi
fi

# ── GitHub provider ─────────────────────────────────────────────────────
if [[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]]; then
  GH_PROVIDER="$SANDBOX_NAME-github"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "Upserting provider $GH_PROVIDER (credential: GITHUB_TOKEN)"
    upsert_cred "$GH_PROVIDER" nemoclaw-github GITHUB_TOKEN "$GITHUB_TOKEN"
  else
    echo "Upserting provider $GH_PROVIDER (credential: GH_TOKEN)"
    upsert_cred "$GH_PROVIDER" nemoclaw-github GH_TOKEN "$GH_TOKEN"
  fi
fi

echo "Provider summary (this sandbox + shared inference):"
openshell provider list 2>&1 | grep -E "($SANDBOX_NAME|compatible-endpoint)" || true
