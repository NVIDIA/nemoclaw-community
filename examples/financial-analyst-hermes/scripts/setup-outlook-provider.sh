#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Configure the finance demo's OpenShell Microsoft Graph provider using the
# same gateway-managed refresh-token pattern as the personal sentiment agent.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"
REPO_ROOT="$(cd "$EXAMPLE_DIR/../.." && pwd)"
SANDBOX_NAME="${1:-${NEMOCLAW_SANDBOX_NAME:-financial-analyst}}"
OUTLOOK_PROVIDER="${OUTLOOK_PROVIDER:-$SANDBOX_NAME-outlook}"
CACHE_PATH="${OUTLOOK_LOGIN_CACHE_PATH:-$EXAMPLE_DIR/.bootstrap/cache/ms-graph-token.json}"

load_env_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
}

load_env_file "$REPO_ROOT/.env"
load_env_file "$EXAMPLE_DIR/.env"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required. Set it in $REPO_ROOT/.env or $EXAMPLE_DIR/.env." >&2
    exit 1
  fi
}

require_env OUTLOOK_TENANT_ID
require_env OUTLOOK_CLIENT_ID
require_env OUTLOOK_TARGET_MAILBOX
require_env OUTLOOK_REPLY_TO

command -v openshell >/dev/null || {
  echo "openshell not found in PATH" >&2
  exit 1
}

if ! openshell settings get --global 2>/dev/null | grep -qE "providers_v2_enabled\s*=\s*true"; then
  echo "Enabling OpenShell provider v2 support at gateway-global scope."
  openshell settings set --global --key providers_v2_enabled --value true --yes
fi

echo "Importing finance Outlook provider profile."
if ! import_out="$(openshell provider profile import --file "$EXAMPLE_DIR/providers/outlook-email.yaml" 2>&1)"; then
  if grep -qi "already exists" <<<"$import_out"; then
    echo "  profile already registered"
  else
    printf '%s\n' "$import_out" >&2
    exit 1
  fi
fi

mode="${OUTLOOK_LOGIN_CACHE:-1}"
case "$mode" in
  0|1|2) ;;
  *)
    echo "Invalid OUTLOOK_LOGIN_CACHE=$mode. Expected 0, 1, or 2." >&2
    exit 1
    ;;
esac

login_json=""
if [[ "$mode" == "1" && -f "$CACHE_PATH" ]]; then
  cached_expires_at_ms="$(python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8"))["expires_at_ms"])
except Exception:
    print(0)
' "$CACHE_PATH" 2>/dev/null || echo 0)"
  now_ms=$(( $(date +%s) * 1000 ))
  if [[ "$cached_expires_at_ms" -gt "$now_ms" ]]; then
    days_left=$(( (cached_expires_at_ms - now_ms) / 1000 / 86400 ))
    echo "Reusing cached Microsoft refresh token (${days_left}d until access-token expiry metadata)."
    login_json="$(cat "$CACHE_PATH")"
  else
    echo "Cached Microsoft token is expired or unreadable; running device-code login."
  fi
fi

if [[ -z "$login_json" ]]; then
  case "$mode" in
    0) echo "OUTLOOK_LOGIN_CACHE=0: device-code login, no on-disk cache." ;;
    2) echo "OUTLOOK_LOGIN_CACHE=2: forcing device-code login and cache rewrite." ;;
  esac

  echo "Sign in as OUTLOOK_TARGET_MAILBOX: $OUTLOOK_TARGET_MAILBOX"
  login_json="$(python3 "$DIR/login-ms-graph.py" \
    --tenant-id "$OUTLOOK_TENANT_ID" \
    --client-id "$OUTLOOK_CLIENT_ID" \
    --login-hint "$OUTLOOK_TARGET_MAILBOX")"

  if [[ "$mode" != "0" ]]; then
    mkdir -p "$(dirname "$CACHE_PATH")"
    umask 077
    printf '%s\n' "$login_json" > "$CACHE_PATH"
  fi
fi

refresh_token="$(printf '%s' "$login_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["refresh_token"])')"
expires_at_ms="$(printf '%s' "$login_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["expires_at_ms"])')"

echo "Upserting provider $OUTLOOK_PROVIDER."
if ! openshell provider get "$OUTLOOK_PROVIDER" >/dev/null 2>&1; then
  openshell provider create \
    --name "$OUTLOOK_PROVIDER" \
    --type nemoclaw-finance-outlook-email \
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

openshell provider refresh rotate "$OUTLOOK_PROVIDER" \
  --credential-key MS_GRAPH_ACCESS_TOKEN

echo
echo "Outlook provider is configured: $OUTLOOK_PROVIDER"
echo "Target mailbox: $OUTLOOK_TARGET_MAILBOX"
echo "Allowed sender: $OUTLOOK_REPLY_TO"
echo
echo "If the sandbox already exists, recreate or restart it with this provider attached."
echo "Then run the bridge with --reply-mode print first, and --reply-mode graph only after validation."
