#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
# SPDX-License-Identifier: Apache-2.0

# Verify the blackwall-guard integration end to end.
#
#   scripts/verify.sh
#
# Four checks, each skippable by environment:
#   1. Unit tests (needs node+npm; run from the repo checkout).
#   2. Egress reachability: can this environment reach the forecast endpoint at
#      all? Any HTTP response — even 401 — proves DNS + network policy + route.
#   3. Credential-injection probe: POSTs with "Authorization: Bearer
#      $BLACKWALL_API_KEY" exactly as the plugin would. Run INSIDE the sandbox
#      where BLACKWALL_API_KEY holds the OpenShell placeholder:
#        - HTTP 2xx            -> the proxy injected the real key at egress. PASS.
#        - 401 missing_api_key -> no Authorization header arrived upstream; the
#                                 placeholder was stripped or no key is set.
#        - 401 (other body)    -> a key arrived but was rejected; the placeholder
#                                 passed through UNREPLACED — injection is not
#                                 configured. (Outside the sandbox with a real
#                                 key, 2xx here just proves the key works.)
#   4. Interception: run HOST-side with SANDBOX_NAME set — checks the sandbox
#      logs for the plugin's deterministic gate line ("[blackwall] <mode> ·
#      <tool> -> <verdict>"), which the hook emits for every gated tool call.
#      If none is present yet, ask the sandboxed agent to run any tool (e.g.
#      "list the files in your workspace") and re-run this check.
set -uo pipefail

BASE_URL="${BLACKWALL_BASE_URL:-https://blackwalltier.com}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

echo "== 1/4 unit tests =="
if command -v npm >/dev/null 2>&1 && [ -f "$HERE/package.json" ]; then
  (cd "$HERE" && npm install --no-audit --no-fund --silent && npx vitest run) || FAIL=1
else
  echo "skipped: npm or package.json not available here (run from the repo checkout)"
fi

echo
echo "== 2/4 egress reachability: $BASE_URL =="
CODE=$(curl -sS -m 30 -o /tmp/blackwall-verify-unauth.json -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/forecast" \
  -H 'Content-Type: application/json' \
  -d '{"action":"verify.sh","inputs":{}}' || echo "000")
if [ "$CODE" = "000" ]; then
  echo "FAIL: no HTTP response — egress to $BASE_URL is blocked or unreachable."
  echo "      If this is the sandbox, apply policy.yaml (scripts/bring-up.sh does)."
  FAIL=1
else
  echo "PASS: endpoint reachable (HTTP $CODE)"
fi

echo
echo "== 3/4 credential-injection probe =="
if [ -z "${BLACKWALL_API_KEY:-}" ]; then
  echo "skipped: BLACKWALL_API_KEY is empty. In the sandbox it should hold the"
  echo "         OpenShell placeholder (providers/blackwall.yaml); outside, a real key."
else
  CODE=$(curl -sS -m 30 -o /tmp/blackwall-verify-auth.json -w '%{http_code}' \
    -X POST "$BASE_URL/api/v1/forecast" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $BLACKWALL_API_KEY" \
    -d '{"action":"verify.sh","inputs":{}}' || echo "000")
  case "$CODE" in
    2*) echo "PASS: HTTP $CODE — a valid key reached the API (proxy injection or real key)." ;;
    401)
      if grep -q missing_api_key /tmp/blackwall-verify-auth.json 2>/dev/null; then
        echo "FAIL: 401 missing_api_key — no Authorization header arrived upstream."
      else
        echo "FAIL: 401 — a key arrived but was rejected. If run in the sandbox, the"
        echo "      placeholder passed through UNREPLACED: provider injection is not active."
      fi
      cat /tmp/blackwall-verify-auth.json 2>/dev/null; echo
      FAIL=1
      ;;
    *) echo "WARN: unexpected HTTP $CODE"; cat /tmp/blackwall-verify-auth.json 2>/dev/null; echo ;;
  esac
fi

echo
echo "== 4/4 interception (host-side, needs SANDBOX_NAME) =="
if [ -z "${SANDBOX_NAME:-}" ] || ! command -v openshell >/dev/null 2>&1; then
  echo "skipped: set SANDBOX_NAME and run where the openshell CLI is available."
else
  if openshell sandbox logs "$SANDBOX_NAME" 2>/dev/null | grep -E "\[blackwall\] (observe|enforce)" | tail -3 | grep -q .; then
    echo "PASS: the hook is intercepting tool calls (gate lines above)."
  else
    echo "PENDING: no gate line in $SANDBOX_NAME logs yet. Ask the sandboxed agent"
    echo "         to run any tool (e.g. 'list the files in your workspace'),"
    echo "         then re-run this check. If lines never appear, the plugin is"
    echo "         not enabled in the agent (see README, 'Install & enable')."
    FAIL=1
  fi
fi

echo
[ "$FAIL" -eq 0 ] && echo "verify: OK" || echo "verify: FAILURES above"
exit "$FAIL"
