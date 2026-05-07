#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
FLOW="browser"
TOKEN_MANAGER_URL="http://localhost:8765"
POLL_TIMEOUT=300
CLIENT_ID=""
TENANT_ID=""
LOGIN_HINT=""
SESSION_ID=""

# ── Usage ─────────────────────────────────────────────────────────────────────
usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") --client-id ID --tenant-id ID [OPTIONS]

Authenticate with the MS Graph token manager and obtain a session UUID.
Works for any Microsoft Graph scenario (Outlook, Teams, SharePoint, etc.).

Required:
  --client-id ID       Entra app registration client ID
  --tenant-id ID       Entra tenant ID

Options:
  --login-hint EMAIL   Pre-fill the Microsoft login page (also enables session
                       deduplication — re-running with the same hint returns the
                       existing session without re-prompting)
  --flow TYPE          Auth flow: browser (default) or device
  --url URL            Token manager base URL (default: http://localhost:8765)
  --timeout SECONDS    Poll timeout in seconds (default: 300)
  --session-id UUID    Existing session UUID to validate; if still valid the
                       script exits 0 without starting a new flow
  -h, --help           Show this help and exit

Output:
  All progress messages are written to stderr.
  SESSION_ID=<uuid> is written to stdout on success, so you can read it
  interactively or capture it:

    SESSION_ID=\$($(basename "$0") --client-id <id> --tenant-id <id>)
    export OUTLOOK_SESSION_UUID="\$SESSION_ID"

Examples:
  # Device code flow
  $(basename "$0") --client-id <id> --tenant-id <id> --flow device

  # Browser flow with login hint
  $(basename "$0") --client-id <id> --tenant-id <id> --login-hint user@example.com

  # Validate an existing session UUID
  $(basename "$0") --client-id <id> --tenant-id <id> --session-id <uuid>
EOF
}

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-id)  CLIENT_ID="$2";          shift 2 ;;
    --tenant-id)  TENANT_ID="$2";          shift 2 ;;
    --login-hint) LOGIN_HINT="$2";         shift 2 ;;
    --flow)       FLOW="$2";               shift 2 ;;
    --url)        TOKEN_MANAGER_URL="$2";  shift 2 ;;
    --timeout)    POLL_TIMEOUT="$2";       shift 2 ;;
    --session-id) SESSION_ID="$2";         shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# ── Validation ────────────────────────────────────────────────────────────────
die() { echo "Error: $*" >&2; exit 1; }

[[ -n "$CLIENT_ID" ]]  || die "--client-id is required"
[[ -n "$TENANT_ID" ]]  || die "--tenant-id is required"
[[ "$FLOW" == "browser" || "$FLOW" == "device" ]] || die "--flow must be 'browser' or 'device'"
[[ "$POLL_TIMEOUT" =~ ^[0-9]+$ ]] || die "--timeout must be a positive integer"
command -v curl >/dev/null 2>&1 || die "curl is required but not found on PATH"
command -v jq   >/dev/null 2>&1 || die "jq is required but not found on PATH"

# ── Emit final result ─────────────────────────────────────────────────────────
emit_session() {
  local sid="$1" user="$2"
  echo "" >&2
  echo "Authenticated as ${user}." >&2
  echo "" >&2
  echo "SESSION_ID=${sid}"
}

# ── Check existing session ────────────────────────────────────────────────────
if [[ -n "$SESSION_ID" ]]; then
  echo "Checking existing session ${SESSION_ID}..." >&2
  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    "${TOKEN_MANAGER_URL}/token?session_id=${SESSION_ID}")
  if [[ "$http_code" == "200" ]]; then
    echo "Session is still valid." >&2
    echo "SESSION_ID=${SESSION_ID}"
    exit 0
  fi
  echo "Session is not valid (HTTP ${http_code}) — starting new auth flow..." >&2
fi

# ── Start auth flow ───────────────────────────────────────────────────────────
echo "Starting ${FLOW} auth flow..." >&2

payload=$(jq -cn \
  --arg client_id "$CLIENT_ID" \
  --arg tenant_id "$TENANT_ID" \
  --arg type      "$FLOW" \
  --arg login_hint "$LOGIN_HINT" \
  '{client_id: $client_id, tenant_id: $tenant_id, type: $type}
   + (if $login_hint != "" then {login_hint: $login_hint} else {} end)')

start_response=$(curl -sf -X POST \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "${TOKEN_MANAGER_URL}/auth/start") \
  || die "Could not reach token manager at ${TOKEN_MANAGER_URL} — is it running?"

session_id=$(echo "$start_response" | jq -r '.session_id // empty')
[[ -n "$session_id" ]] || die "Token manager returned no session_id: ${start_response}"

start_status=$(echo "$start_response" | jq -r '.status // empty')

if [[ "$start_status" == "already_authenticated" ]]; then
  username=$(echo "$start_response" | jq -r '.username // "unknown"')
  emit_session "$session_id" "$username"
  exit 0
fi

# ── Display auth prompt ───────────────────────────────────────────────────────
if [[ "$FLOW" == "browser" ]]; then
  auth_uri=$(echo "$start_response" | jq -r '.auth_uri // empty')
  [[ -n "$auth_uri" ]] || die "No auth_uri in /auth/start response: ${start_response}"
  echo "" >&2
  echo "Open this URL in your browser to authenticate:" >&2
  echo "  ${auth_uri}" >&2
  echo "" >&2
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$auth_uri" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$auth_uri" >/dev/null 2>&1 || true
  fi
else
  user_code=$(echo "$start_response" | jq -r '.user_code // empty')
  device_url=$(echo "$start_response" | jq -r '.url // empty')
  [[ -n "$user_code" ]] || die "No user_code in /auth/start response: ${start_response}"
  echo "" >&2
  echo "Go to:  ${device_url}" >&2
  echo "Enter:  ${user_code}" >&2
  echo "" >&2
fi

echo "Waiting for authentication (timeout: ${POLL_TIMEOUT}s)..." >&2

# ── Poll ──────────────────────────────────────────────────────────────────────
deadline=$(( $(date +%s) + POLL_TIMEOUT ))

while [[ $(date +%s) -lt $deadline ]]; do
  poll_response=$(curl -sf \
    "${TOKEN_MANAGER_URL}/auth/poll?session_id=${session_id}" 2>/dev/null) || true

  if [[ -z "$poll_response" ]]; then
    sleep 5
    continue
  fi

  poll_status=$(echo "$poll_response" | jq -r '.status // empty')

  case "$poll_status" in
    complete)
      username=$(echo "$poll_response" | jq -r '.username // "unknown"')
      emit_session "$session_id" "$username"
      exit 0
      ;;
    expired|error)
      msg=$(echo "$poll_response" | jq -r '.message // .status')
      die "Authentication failed: ${msg}"
      ;;
    pending|*)
      sleep 5
      ;;
  esac
done

die "Authentication timed out after ${POLL_TIMEOUT}s. Run this script again to retry."
