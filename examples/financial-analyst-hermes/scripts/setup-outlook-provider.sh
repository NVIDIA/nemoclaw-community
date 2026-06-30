#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

dotenv_value() {
  local name="$1" file value
  for file in "$EXAMPLE_DIR/.env" "$REPO_ROOT/.env"; do
    [[ -f "$file" ]] || continue
    value="$(python3 - "$file" "$name" <<'PY'
from pathlib import Path
import sys

path, wanted = Path(sys.argv[1]), sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() == wanted:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        print(value)
        raise SystemExit
PY
    )"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return
    fi
  done
}

load_setting() {
  local name value
  name="$1"
  value="${!name:-}"
  [[ -n "$value" ]] || value="$(dotenv_value "$name")"
  printf -v "$name" '%s' "$value"
  export "${name?}"
}

for setting_name in \
  OUTLOOK_TENANT_ID OUTLOOK_CLIENT_ID OUTLOOK_TARGET_MAILBOX OUTLOOK_REPLY_TO \
  OUTLOOK_LOGIN_CACHE; do
  load_setting "$setting_name"
done

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

mkdir -p "$EXAMPLE_DIR/.runtime"
staged_provider="$EXAMPLE_DIR/.runtime/outlook-provider.yaml"
python3 - "$EXAMPLE_DIR/providers/outlook-email.yaml" \
  "$staged_provider" "$OUTLOOK_TARGET_MAILBOX" <<'PY'
from pathlib import Path
import sys
from urllib.parse import quote

source, target, mailbox = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
target.write_text(
    source.read_text(encoding="utf-8").replace(
        "__OUTLOOK_MAILBOX__", quote(mailbox, safe="")
    ),
    encoding="utf-8",
)
PY

command -v openshell >/dev/null || {
  echo "openshell not found in PATH" >&2
  exit 1
}
command -v nemohermes >/dev/null || {
  echo "nemohermes not found in PATH; run scripts/demo.sh up first" >&2
  exit 1
}

if ! openshell settings get --global 2>/dev/null | grep -qE "providers_v2_enabled\s*=\s*true"; then
  echo "Enabling OpenShell provider v2 support at gateway-global scope."
  openshell settings set --global --key providers_v2_enabled --value true --yes
fi

echo "Importing finance Outlook provider profile."
openshell provider profile delete nemoclaw-finance-outlook-email >/dev/null 2>&1 || true
if ! import_out="$(openshell provider profile import --file "$staged_provider" 2>&1)"; then
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

# OpenShell 0.0.44 accepts refresh material only as KEY=VALUE arguments. Keep
# this command short-lived, never enable shell tracing, and use a single-user
# demo host. --secret-material-key prevents the gateway from exposing it later.
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
echo "Attaching the provider and read/reply policy to $SANDBOX_NAME."
if ! attach_out="$(openshell sandbox provider attach "$SANDBOX_NAME" "$OUTLOOK_PROVIDER" 2>&1)"; then
  if ! grep -qi "already" <<<"$attach_out"; then
    printf '%s\n' "$attach_out" >&2
    exit 1
  fi
fi
staged_policy="$EXAMPLE_DIR/.runtime/outlook-policy.yaml"
python3 - "$EXAMPLE_DIR/presets/financial-outlook-mailbox.yaml" \
  "$staged_policy" "$OUTLOOK_TARGET_MAILBOX" <<'PY'
from pathlib import Path
import sys
from urllib.parse import quote

source, target, mailbox = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
rendered = source.read_text(encoding="utf-8").replace(
    "__OUTLOOK_MAILBOX__", quote(mailbox, safe="")
)
target.write_text(rendered, encoding="utf-8")
PY
nemohermes "$SANDBOX_NAME" policy-add --from-file "$staged_policy" --yes
nemohermes "$SANDBOX_NAME" upload \
  "$DIR/outlook_finance_bridge.py" /sandbox/outlook_finance_bridge.py

echo "Outlook is attached. Validate in print mode before enabling Graph replies."
