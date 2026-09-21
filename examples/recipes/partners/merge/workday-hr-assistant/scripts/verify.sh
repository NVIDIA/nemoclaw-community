#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Check allowed reads, excluded tools, runtime scope, and optional revocation.
# Agent Handler enforces tool access; OpenShell protects the runtime credential.
# Agent text is not proof of tool use: inspect the transcript for case 4b.
# Exit nonzero if any executed check fails; report inconclusive cases as skips.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v curl    >/dev/null || { echo "curl not in PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not in PATH — needed to read JSON-RPC replies" >&2; exit 1; }

require_var MERGE_AH_MCP_TOKEN
require_var MERGE_AH_TOOL_PACK_ID
require_var MERGE_AH_REGISTERED_USER_ID

SYSTEM_NAME="${SYSTEM_NAME:-the connected system}"
READER_TOOL="${READER_TOOL:-workday__list_workers}"
EXCLUDED_TOOL="${EXCLUDED_TOOL:-workday__request_one_time_payment}"
MCP_URL="$(ah_mcp_url)"

PASS=0; FAIL=0; SKIP=0
ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
skip() { echo "  SKIP  $1"; SKIP=$((SKIP+1)); }

# Open an MCP session against $1 (a URL) and echo its Mcp-Session-Id.
# Returns non-zero when initialize does not yield a session.
mcp_session() {
  local url="$1" headers
  headers="$(mktemp)"
  curl -s -o /dev/null -D "$headers" --max-time 30 -X POST "$url" \
    -H @- \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"workday-hr-verify","version":"1"}}}' \
    2>/dev/null <<< "Authorization: Bearer $MERGE_AH_MCP_TOKEN" || true
  local sid
  sid="$(grep -i '^mcp-session-id:' "$headers" | awk '{print $2}' | tr -d '\r')"
  rm -f "$headers"
  [[ -n "$sid" ]] || return 1
  printf '%s' "$sid"
}

# Return the initialize HTTP status. Transport errors remain failures, so callers
# cannot mistake an unreachable endpoint for an authorization denial.
mcp_initialize_status() {
  curl -s --max-time 30 -o "${2:-/dev/null}" -w '%{http_code}' -X POST "$1" \
    -H @- \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"workday-hr-verify","version":"1"}}}' <<< "Authorization: Bearer $MERGE_AH_MCP_TOKEN"
}

# Call an MCP method against $1 with session $2 and raw JSON params $4.
# Echoes the decoded JSON-RPC payload (SSE `data:` framing stripped).
mcp_call() {
  local url="$1" sid="$2" method="$3" params="${4:-{\}}"
  curl -s --max-time 45 -X POST "$url" \
    -H @- \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: $sid" \
    --data "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"$method\",\"params\":$params}" \
    2>/dev/null <<< "Authorization: Bearer $MERGE_AH_MCP_TOKEN" | sed 's/^data: //' | grep -v '^$' | tail -n 1
}

# Revocation is a separate mode: an invalid key cannot run the live cases.
if [[ "${EXPECT_REVOKED:-0}" == "1" ]]; then
  if HTTP_STATUS="$(mcp_initialize_status "$MCP_URL")"; then
    case "$HTTP_STATUS" in
      401|403) ok "case 5: the revoked key is refused (HTTP $HTTP_STATUS)" ;;
      *) bad "case 5: expected authorization denial, got HTTP $HTTP_STATUS" ;;
    esac
  else
    bad "case 5: transport failure cannot establish revocation"
  fi
  echo "passed=$PASS failed=$FAIL skipped=$SKIP"
  [[ "$FAIL" -eq 0 ]]
  exit $?
fi

# Extract the advertised tool names from a tools/list reply.
tool_names() {
  python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
for t in d.get("result",{}).get("tools",[]): print(t.get("name",""))
'
}

# True when a tools/call reply is an error (isError, or a JSON-RPC error).
is_error_reply() {
  python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("malformed"); sys.exit(0)
if not isinstance(d, dict): print("malformed"); sys.exit(0)
if "error" in d: print("rpc_error"); sys.exit(0)
r=d.get("result")
if not isinstance(r, dict) or not isinstance(r.get("content"), list):
    print("malformed"); sys.exit(0)
if r.get("isError"): print("tool_error"); sys.exit(0)
print("ok")
'
}

# Reason string from an Agent Handler error payload, when present.
error_reason() {
  python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
for item in d.get("result",{}).get("content",[]):
    try: print(json.loads(item.get("text","")).get("error_reason",""))
    except Exception: pass
'
}

echo "== Section A: authorization boundary (Agent Handler, scoped key) =="
echo "Tool Pack:       $MERGE_AH_TOOL_PACK_ID"
echo "Registered User: $MERGE_AH_REGISTERED_USER_ID"
echo

SID="$(mcp_session "$MCP_URL")" || { echo "  FAIL  could not open an MCP session — check the scoped key" >&2; exit 1; }
LIST="$(mcp_call "$MCP_URL" "$SID" tools/list '{}')"
NAMES="$(printf '%s' "$LIST" | tool_names)"
COUNT="$(printf '%s' "$NAMES" | grep -c . || true)"
echo "Advertised tools: $COUNT"

# Case 1 — the reader tool is advertised.
if printf '%s\n' "$NAMES" | grep -Fxq "$READER_TOOL"; then
  ok "case 1: '$READER_TOOL' is advertised to this role"
else
  bad "case 1: '$READER_TOOL' is NOT advertised — the Tool Pack is missing the reader tool"
fi

# Case 2 — the excluded tool is absent from the advertised set. This is the
# RBAC assertion: the capability does not exist for this role.
if printf '%s\n' "$NAMES" | grep -Fxq "$EXCLUDED_TOOL"; then
  bad "case 2: '$EXCLUDED_TOOL' IS advertised — the Tool Pack is too wide for an hr-reader role"
else
  ok "case 2: '$EXCLUDED_TOOL' is not advertised to this role"
fi

# Case 3 — calling the excluded tool is refused by Agent Handler. Runs even
# when case 2 passes: absence from the catalog and refusal on call are
# different properties, and a client can always name a tool directly.
# An error alone is NOT a pass: a missing connector credential also errors. Only an
# authorization refusal proves the boundary. `reauth_required` means the call
# died on the credential before authorization was decided — inconclusive.
CALL="$(mcp_call "$MCP_URL" "$SID" tools/call "{\"name\":\"$EXCLUDED_TOOL\",\"arguments\":{}}")"
VERDICT="$(printf '%s' "$CALL" | is_error_reply)"
REASON="$(printf '%s' "$CALL" | error_reason)"
case "$VERDICT:$REASON" in
  ok:*)
    bad "case 3: '$EXCLUDED_TOOL' was ACCEPTED — the authorization boundary did not hold" ;;
  *:permission_denied|*:forbidden|*:unauthorized|*:tool_not_found)
    ok "case 3: '$EXCLUDED_TOOL' refused at the authorization boundary ($REASON)" ;;
  *:reauth_required)
    skip "case 3: inconclusive — the call failed on the missing $SYSTEM_NAME credential, not on authorization" ;;
  *)
    skip "case 3: inconclusive — refused with an unrecognized reason (${REASON:-$VERDICT})" ;;
esac

echo
echo "== Section B: live read =="
# Probe with the reader tool itself. A minimally-scoped pack excludes
# validate_credential, so using it here would report a missing credential when
# the real cause is correct scoping.
READ="$(mcp_call "$MCP_URL" "$SID" tools/call "{\"name\":\"$READER_TOOL\",\"arguments\":{}}")"
READ_REASON="$(printf '%s' "$READ" | error_reason)"
if [[ "$READ_REASON" == "reauth_required" ]]; then
  skip "case 4: $SYSTEM_NAME is not connected for this Registered User — run the authenticate tool and link the account"
else
  if [[ "$(printf '%s' "$READ" | is_error_reply)" == "ok" ]]; then
    ok "case 4: '$READER_TOOL' returned a result over MCP"
  else
    bad "case 4: '$READER_TOOL' failed (${READ_REASON:-unknown reason})"
  fi

  # Agent path: the same read, driven through the sandbox as the agent would.
  # Evidence of integration, never of a security property.
  if command -v nemoclaw >/dev/null && sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
    if TURN="$(nemoclaw "$NEMOCLAW_SANDBOX_NAME" agent --agent main \
      -m "Use the $MCP_SERVER_NAME MCP server to list workers. Reply with the first five worker names only." 2>&1)"; then
      if [[ -z "${TURN//[[:space:]]/}" ]] || printf '%s' "$TURN" | grep -qiE 'error|not available|cannot'; then
        bad "case 4b: the agent returned no usable read (inspect the transcript locally)"
      else
        skip "case 4b: agent turn completed; inspect its tool-call transcript to confirm a Workday read"
      fi
    else
      bad "case 4b: the agent command failed (inspect the transcript locally)"
    fi
  else
    skip "case 4b: sandbox '$NEMOCLAW_SANDBOX_NAME' not available for an agent turn"
  fi
fi

echo
echo "== Section D: key scope =="
# The runtime key must not be able to widen its own access. These cases fail on
# a management key, which is the point: a management key in the sandbox
# registration would silently defeat the Tool Pack boundary above.

# Case 6 — the key cannot perform management operations.
ESC="$(curl -s --max-time 25 -o /dev/null -w '%{http_code}' -X POST "$AH_BASE_URL/api/v1/tool-packs/" \
  -H @- -H "Content-Type: application/json" \
  --data '{"name":"escalation-probe","description":"must be refused","connectors":[{"slug":"workday","tool_names":["request_one_time_payment"]}]}' 2>/dev/null <<< "Authorization: Bearer $MERGE_AH_MCP_TOKEN" || true)"
if [[ "$ESC" == "401" || "$ESC" == "403" ]]; then
  ok "case 6: the runtime key cannot create a Tool Pack (HTTP $ESC)"
else
  bad "case 6: the runtime key reached Tool Pack creation (HTTP $ESC) — it carries management scope"
fi

# Case 7 — the key cannot address a Tool Pack it is not bound to.
if [[ -n "${OTHER_TOOL_PACK_ID:-}" ]]; then
  OTHER_URL="$AH_BASE_URL/api/v1/tool-packs/$OTHER_TOOL_PACK_ID/registered-users/$MERGE_AH_REGISTERED_USER_ID/mcp"
  DENIAL_BODY="$(mktemp)"
  if HTTP_STATUS="$(mcp_initialize_status "$OTHER_URL" "$DENIAL_BODY")"; then
    # Agent Handler hides out-of-scope resources behind a specific JSON-RPC 404.
    # A generic missing-resource response is not evidence of authorization.
    SCOPE_DENIAL="$(python3 - "$DENIAL_BODY" <<'PYCODE'
import json, sys
try:
    text = open(sys.argv[1]).read().strip()
    if text.startswith("data: "):
        text = text[6:]
    error = json.loads(text).get("error", {})
    print("yes" if error.get("code") == -32601 and error.get("message") == "Resource not in API key scope." else "no")
except (ValueError, AttributeError):
    print("no")
PYCODE
)"
    case "$HTTP_STATUS" in
      401|403) ok "case 7: the key cannot address an unbound Tool Pack (HTTP $HTTP_STATUS)" ;;
      404)
        if [[ "$SCOPE_DENIAL" == "yes" ]]; then
          ok "case 7: the key cannot address an unbound Tool Pack (HTTP 404, explicit scope denial)"
        else
          bad "case 7: HTTP 404 without an explicit scope denial"
        fi ;;
      *) bad "case 7: expected authorization denial, got HTTP $HTTP_STATUS" ;;
    esac
  else
    bad "case 7: transport failure cannot establish Tool Pack isolation"
  fi
  rm -f "$DENIAL_BODY"
else
  skip "case 7: set OTHER_TOOL_PACK_ID to a pack this key is not bound to"
fi

echo
echo "== Section C: key revocation =="
skip "case 5: revoke the key in the Agent Handler dashboard, then re-run with EXPECT_REVOKED=1"

echo
echo "passed=$PASS failed=$FAIL skipped=$SKIP"
[[ "$FAIL" -eq 0 ]] || exit 1
