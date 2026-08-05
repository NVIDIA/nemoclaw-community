#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Print a compact, non-secret health report. --repair runs the watchdog after it.

set -euo pipefail
AUTOHEAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$AUTOHEAL_DIR/lib.sh"

REPAIR=false
case "${1:-}" in
  "") ;;
  --repair) REPAIR=true ;;
  -h|--help)
    printf 'Usage: bash scripts/autoheal/sanity-check.sh [--repair]\n'
    exit 0
    ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac

failures=0
report() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS  %s\n' "$label"
  else
    printf 'FAIL  %s\n' "$label"
    failures=$((failures + 1))
  fi
}

slack_socket_probe() {
  openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc '
    source /sandbox/.hermes-data/.env >/dev/null 2>&1 || source /sandbox/.hermes/.env >/dev/null 2>&1
    body="$(curl -sS --max-time 12 -X POST -H "Authorization: Bearer ${SLACK_APP_TOKEN}" https://slack.com/api/apps.connections.open)" || exit 1
    python3 -c "import json,sys; raise SystemExit(0 if json.loads(sys.argv[1]).get(\"ok\") else 1)" "$body"
  ' >/dev/null 2>&1
}

report "sandbox ${AUTOHEAL_SANDBOX_NAME} is Ready" sandbox_ready
report "sandbox Hermes gateway" sandbox_gateway_ok
report "host gateway forward" host_gateway_ok

if proxy_is_configured; then
  report "host TLS proxy service" systemctl --user is-active --quiet nemoclaw-hermes-proxy.service
  report "host TLS proxy listener" curl -sS -o /dev/null --max-time 5 "http://127.0.0.1:${AUTOHEAL_PROXY_PORT}/"
fi

if [[ -n "${COMPATIBLE_API_KEY:-${OPENAI_API_KEY:-}}" ]] && sandbox_ready; then
  report "Hermes inference" openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc \
    'HERMES_HOME=/sandbox/.hermes-data hermes -z "Reply with OK." >/dev/null'
fi

if [[ -n "${SLACK_APP_TOKEN:-}" ]] && sandbox_ready; then
  report "Slack Socket Mode" slack_socket_probe
fi

if [[ -n "${OUTLOOK_CLIENT_ID:-}" ]] && sandbox_ready; then
  report "Outlook Graph search" openshell sandbox exec --name "$AUTOHEAL_SANDBOX_NAME" -- bash -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py --since 1d --top 1 >/dev/null'
fi

if "$REPAIR" && (( failures > 0 )); then
  printf '\nRunning watchdog repair after %s failed check(s).\n' "$failures"
  bash "$AUTOHEAL_DIR/watchdog.sh"
fi

if (( failures > 0 )); then
  printf '\nSanity check found %s failed check(s).\n' "$failures" >&2
  exit 1
fi
printf '\nSanity check passed.\n'
