#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Phase 3 of 4: Import v2 provider profiles and upsert this sandbox's providers.
# Outlook providers run an interactive Microsoft device-code login the first
# time (refresh token cached under .bootstrap/cache/, ignored by .gitignore).
# OUTLOOK_LOGIN_CACHE controls the cache: 0=off, 1=use (default), 2=force-rewrite.

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
for profile_id in nemoclaw-outlook-email nemoclaw-slack nemoclaw-github \
                  nemoclaw-atif-export-relay; do
  openshell provider profile delete "$profile_id" >/dev/null 2>&1 || true
done
# Import each active profile by name. nemoclaw-compatible-endpoint is a
# forward-looking placeholder (see the header in providers/compatible-endpoint.yaml)
# and is deliberately NOT imported — the active inference path uses the
# built-in `nvidia` v2 profile via `openshell inference set` below.
#
# atif-export-relay.yaml carries __ATIF_RELAY_HOST/PORT__ placeholders so
# the endpoint tracks ATIF_RELAY_ENDPOINT — stage through sed before import.
STAGED_RELAY_PROFILE="$EXAMPLE_DIR/providers/.atif-export-relay.staged.yaml"
trap 'rm -f "$STAGED_RELAY_PROFILE"' EXIT
for profile_file in outlook-email.yaml slack.yaml github.yaml atif-export-relay.yaml; do
  src="$EXAMPLE_DIR/providers/$profile_file"
  if [[ "$profile_file" == "atif-export-relay.yaml" ]]; then
    sed -e "s|__ATIF_RELAY_HOST__|$ATIF_RELAY_HOST|g" \
        -e "s|__ATIF_RELAY_PORT__|$ATIF_RELAY_PORT|g" \
        "$src" > "$STAGED_RELAY_PROFILE"
    src="$STAGED_RELAY_PROFILE"
  fi
  openshell provider profile import --file "$src"
done

# ── Inference provider (built-in nvidia v2 profile via inference.local) ─
INFERENCE_KEY="${OPENAI_API_KEY:-${COMPATIBLE_API_KEY:-}}"
if [[ -n "$INFERENCE_KEY" ]]; then
  INFERENCE_PROVIDER="compatible-endpoint"
  INFERENCE_MODEL="${NEMOCLAW_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
  INFERENCE_BASE_URL="${NEMOCLAW_ENDPOINT_URL:-${OPENAI_BASE_URL:-https://integrate.api.nvidia.com/v1}}"
  echo "Upserting inference provider $INFERENCE_PROVIDER (model: $INFERENCE_MODEL, base: $INFERENCE_BASE_URL)"

  # Recreate if existing provider has the wrong type (e.g. left over from the
  # nemoclaw-compatible-endpoint direct-egress experiment).
  if openshell provider get "$INFERENCE_PROVIDER" >/dev/null 2>&1 \
       && ! provider_type_matches "$INFERENCE_PROVIDER" nvidia; then
    echo "  $INFERENCE_PROVIDER exists with wrong type; recreating as nvidia"
    openshell provider delete "$INFERENCE_PROVIDER" >/dev/null
  fi

  # Map our env var (OPENAI_API_KEY / COMPATIBLE_API_KEY) to the nvidia
  # profile's expected NVIDIA_API_KEY at provider-create time.
  if openshell provider get "$INFERENCE_PROVIDER" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" NVIDIA_API_KEY="$INFERENCE_KEY" \
      openshell provider update "$INFERENCE_PROVIDER" \
        --credential NVIDIA_API_KEY --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL"
  else
    env -i HOME="$HOME" PATH="$PATH" NVIDIA_API_KEY="$INFERENCE_KEY" \
      openshell provider create --name "$INFERENCE_PROVIDER" --type nvidia \
        --credential NVIDIA_API_KEY --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL"
  fi

  echo "Setting cluster inference: provider=$INFERENCE_PROVIDER model=$INFERENCE_MODEL"
  openshell inference set --no-verify --provider "$INFERENCE_PROVIDER" --model "$INFERENCE_MODEL"
else
  echo "WARNING: neither OPENAI_API_KEY nor COMPATIBLE_API_KEY is set — skipping inference provider. The agent will have no LLM." >&2
fi

# ── Outlook provider with gateway-managed OAuth refresh ─────────────────
if [[ -n "${OUTLOOK_CLIENT_ID:-}" ]]; then
  OUTLOOK_PROVIDER="$SANDBOX_NAME-outlook"
  OUTLOOK_LOGIN_CACHE_PATH="$EXAMPLE_DIR/.bootstrap/cache/ms-graph-token.json"
  case "${OUTLOOK_LOGIN_CACHE:-1}" in
    0|1|2) ;;
    *) echo "Invalid OUTLOOK_LOGIN_CACHE=$OUTLOOK_LOGIN_CACHE (expected 0, 1, or 2)" >&2; exit 1 ;;
  esac

  login_json=""
  mode="${OUTLOOK_LOGIN_CACHE:-1}"

  # Mode 1: try the cache, with a freshness check on expires_at_ms.
  if [[ "$mode" == "1" && -f "$OUTLOOK_LOGIN_CACHE_PATH" ]]; then
    cached_expires_at_ms="$(python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))["expires_at_ms"])
except Exception:
    print(0)
' "$OUTLOOK_LOGIN_CACHE_PATH" 2>/dev/null || echo 0)"
    now_ms=$(( $(date +%s) * 1000 ))
    if [[ "$cached_expires_at_ms" -gt "$now_ms" ]]; then
      days_left=$(( (cached_expires_at_ms - now_ms) / 1000 / 86400 ))
      echo "Reusing cached Microsoft refresh token at $OUTLOOK_LOGIN_CACHE_PATH (${days_left}d until expiry)"
      login_json="$(cat "$OUTLOOK_LOGIN_CACHE_PATH")"
    else
      echo "Cached refresh token at $OUTLOOK_LOGIN_CACHE_PATH is expired or unreadable; re-running device-code login"
    fi
  fi

  # Fall through to device-code login: mode 0, mode 2, or mode 1 cache miss/stale.
  if [[ -z "$login_json" ]]; then
    case "$mode" in
      0) echo "OUTLOOK_LOGIN_CACHE=0 — device-code login, no on-disk cache" ;;
      2) echo "OUTLOOK_LOGIN_CACHE=2 — forcing device-code login + cache rewrite" ;;
    esac
    login_hint_args=()
    [[ -n "${OUTLOOK_TARGET_MAILBOX:-}" ]] && login_hint_args+=(--login-hint "$OUTLOOK_TARGET_MAILBOX")
    login_json="$(python3 "$DIR/login-ms-graph.py" \
      --tenant-id "$OUTLOOK_TENANT_ID" \
      --client-id "$OUTLOOK_CLIENT_ID" \
      "${login_hint_args[@]}")"
    # Modes 1 and 2 write the cache; mode 0 doesn't.
    if [[ "$mode" != "0" ]]; then
      mkdir -p "$(dirname "$OUTLOOK_LOGIN_CACHE_PATH")"
      umask 077
      printf '%s\n' "$login_json" > "$OUTLOOK_LOGIN_CACHE_PATH"
    fi
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
  echo "Upserting provider $SLACK_PROVIDER (credentials: SLACK_BOT_TOKEN + SLACK_APP_TOKEN)"
  upsert_cred "$SLACK_PROVIDER" nemoclaw-slack \
    "SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN:-}" \
    "SLACK_APP_TOKEN=${SLACK_APP_TOKEN:-}"
fi

# ── GitHub provider ─────────────────────────────────────────────────────
if [[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]]; then
  GH_PROVIDER="$SANDBOX_NAME-github"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "Upserting provider $GH_PROVIDER (credential: GITHUB_TOKEN)"
    upsert_cred "$GH_PROVIDER" nemoclaw-github "GITHUB_TOKEN=$GITHUB_TOKEN"
  else
    echo "Upserting provider $GH_PROVIDER (credential: GH_TOKEN)"
    upsert_cred "$GH_PROVIDER" nemoclaw-github "GH_TOKEN=$GH_TOKEN"
  fi
fi

# ── ATIF object-storage provider (bearer token for atif-export-relay) ───
# Only configured when atif_remote_enabled returns true (i.e.,
# ATIF_STORAGE_BACKEND=minio or s3). For BACKEND=local or unset, this
# block is skipped and ATIF writes go to the sandbox's /tmp/atif. The
# credential is a per-VM bearer token: the sandbox env carries a
# placeholder (`openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN`), the L7
# proxy substitutes the real value on egress, and atif-export-relay
# validates it against the ATIF_RELAY_AUTH_TOKEN env var passed to the
# relay container (see extras/docker-compose.yml).
if atif_remote_enabled; then
  # Generate the per-VM bearer token on first bring-up; reuse from .env
  # on subsequent ones. Delete the .env line to force re-issuance.
  token_minted_this_run=0
  if [[ -z "${ATIF_RELAY_AUTH_TOKEN:-}" ]]; then
    ATIF_RELAY_AUTH_TOKEN="atif-$(openssl rand -hex 24)"
    {
      echo ""
      echo "# Generated by scripts/02-providers.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "ATIF_RELAY_AUTH_TOKEN=$ATIF_RELAY_AUTH_TOKEN"
    } >> "$EXAMPLE_DIR/.env"
    export ATIF_RELAY_AUTH_TOKEN
    token_minted_this_run=1
    echo "Issued new ATIF_RELAY_AUTH_TOKEN, appended to .env"
    # Force-recreate the relay container so it picks up the new token.
    docker compose -f "$EXAMPLE_DIR/extras/docker-compose.yml" \
      --profile "$ATIF_STORAGE_BACKEND" \
      up -d --force-recreate atif-export-relay >/dev/null 2>&1 || true
  fi

  STORAGE_PROVIDER="$SANDBOX_NAME-atif-export-relay"
  # Idempotency: every `provider update --credential` bumps the credential's
  # internal revision, which invalidates any running sandbox's revisioned
  # placeholder (env vars hold `openshell:resolve:env:v<N>_KEY`, set at
  # sandbox-create time). Re-running this script after a bring-up would
  # silently break ATIF export. Only upsert when the token was just minted
  # or when the provider doesn't yet carry the credential — `provider get`
  # redacts values, so the credential-key presence is the strongest check.
  needs_upsert=0
  if [[ "$token_minted_this_run" == "1" ]]; then
    needs_upsert=1
  elif ! openshell provider get "$STORAGE_PROVIDER" >/dev/null 2>&1; then
    needs_upsert=1
  elif ! openshell provider get "$STORAGE_PROVIDER" 2>/dev/null \
       | sed $'s/\x1b\\[[0-9;]*m//g' \
       | grep -qE "^[[:space:]]*Credential keys:.*\\bATIF_RELAY_AUTH_TOKEN\\b"; then
    needs_upsert=1
  fi

  if [[ "$needs_upsert" == "1" ]]; then
    echo "Upserting provider $STORAGE_PROVIDER (credential: ATIF_RELAY_AUTH_TOKEN)"
    upsert_cred "$STORAGE_PROVIDER" nemoclaw-atif-export-relay \
      "ATIF_RELAY_AUTH_TOKEN=$ATIF_RELAY_AUTH_TOKEN"
  else
    echo "Reusing existing $STORAGE_PROVIDER (credential unchanged; skipping update to preserve sandbox placeholder revision)"
  fi
fi

echo "Provider summary (this sandbox + shared inference):"
openshell provider list 2>&1 | grep -E "($SANDBOX_NAME|compatible-endpoint)" || true
