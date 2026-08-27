#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Validate Slack credentials before onboarding spends a rebuild on them.
#
# NemoClaw validates both tokens live during onboarding, against auth.test and
# apps.connections.open. If either is rejected, Slack is not enabled. This runs
# the same two checks first, plus scope and optional channel checks.
#
#   export SLACK_BOT_TOKEN=xoxb-...  SLACK_APP_TOKEN=xapp-...
#   ./scripts/check-slack-tokens.sh                          # both tokens; the usual case
#   ./scripts/check-slack-tokens.sh --channel <CHANNEL_ID>   # only if you also use a channel
#
# Tokens are read from the environment and passed to curl over stdin, so they do not appear
# in the process table or your shell history. Nothing is written to disk.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

CHANNEL=""
FAILED=0
WARNED=0

# Scopes the bundled app manifest declares. An under-scoped app connects cleanly and then
# never receives the mention, which is the failure that wastes an afternoon.
REQUIRED_SCOPES="app_mentions:read chat:write channels:history channels:read groups:history im:history im:read im:write"

usage() {
  cat <<'EOF'
Usage: check-slack-tokens.sh [--channel CID]

  --channel CID   Also verify this channel exists and the bot is a member
  -h, --help      Show this help

Reads SLACK_BOT_TOKEN and SLACK_APP_TOKEN from the environment.
Exit 0 if NemoClaw onboarding would accept these credentials.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL=${2:-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 3 ;;
  esac
done

command -v curl >/dev/null 2>&1 || { printf 'curl is required\n' >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { printf 'python3 is required\n' >&2; exit 3; }

pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=$((FAILED + 1)); }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; WARNED=$((WARNED + 1)); }

# Call Slack with the token supplied over stdin rather than argv.
slack_call() {
  local method=$1 token=$2 verb=${3:-GET} extra=${4:-}
  {
    printf 'url = "https://slack.com/api/%s"\n' "$method"
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'silent\n'
    printf 'show-error\n'
    printf 'dump-header = "/dev/stderr"\n'
    [ "$verb" = "POST" ] && printf 'request = "POST"\ndata = ""\n'
    [ -n "$extra" ] && printf '%s\n' "$extra"
  } | curl --config - 2>/tmp/.slackhdr.$$
}

field() { python3 -c 'import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1], ""))
except Exception: print("")' "$1"; }

printf '\nSlack credential check\n\n'

# ---- bot token -------------------------------------------------------------------------
printf 'Bot token (SLACK_BOT_TOKEN)\n'
if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
  fail "not set. This is the token that needs the workspace-admin install."
else
  bot_shape=ok
  case "$SLACK_BOT_TOKEN" in
    xoxb-*) pass "format looks right (xoxb-)" ;;
    xoxp-*) fail "this is a user token, not a bot token. NemoClaw needs the Bot User OAuth Token."
            bot_shape=bad ;;
    *)      fail "must start with xoxb-. NemoClaw rejects other shapes on format alone."
            bot_shape=bad ;;
  esac

  [ "$bot_shape" = ok ] || SLACK_BOT_TOKEN=""
fi

if [ -n "${SLACK_BOT_TOKEN:-}" ]; then
  body=$(slack_call auth.test "$SLACK_BOT_TOKEN")
  if [ "$(printf '%s' "$body" | field ok)" = "True" ] || [ "$(printf '%s' "$body" | field ok)" = "true" ]; then
    team=$(printf '%s' "$body" | field team)
    user=$(printf '%s' "$body" | field user)
    pass "auth.test accepted it — workspace '$team', bot '$user'"

    granted=$(grep -i '^x-oauth-scopes:' /tmp/.slackhdr.$$ 2>/dev/null | cut -d: -f2- | tr -d ' \r')
    if [ -n "$granted" ]; then
      missing=""
      for s in $REQUIRED_SCOPES; do
        case ",$granted," in *",$s,"*) ;; *) missing="$missing $s" ;; esac
      done
      if [ -n "$missing" ]; then
        warn "missing scopes:$missing"
        warn "the app will connect and then never see your mention. Add these, reinstall, re-run."
      else
        pass "all scopes the manifest declares are granted"
      fi
    fi
  else
    err=$(printf '%s' "$body" | field error)
    case "$err" in
      not_authed|invalid_auth) fail "auth.test rejected it (invalid_auth). Token is wrong or revoked." ;;
      account_inactive)        fail "the app was uninstalled from the workspace." ;;
      "")                      fail "no response from Slack. Check egress from this host." ;;
      *)                       fail "auth.test returned: $err" ;;
    esac
  fi
fi

# ---- app token -------------------------------------------------------------------------
printf '\nApp-level token (SLACK_APP_TOKEN)\n'
if [ -z "${SLACK_APP_TOKEN:-}" ]; then
  fail "not set. Basic Information -> App-Level Tokens, with the connections:write scope."
else
  app_shape=ok
  case "$SLACK_APP_TOKEN" in
    xapp-*) pass "format looks right (xapp-)" ;;
    *)      fail "must start with xapp-. A bot token here is the common mix-up."; app_shape=bad ;;
  esac

  [ "$app_shape" = ok ] || SLACK_APP_TOKEN=""
fi

if [ -n "${SLACK_APP_TOKEN:-}" ]; then
  body=$(slack_call apps.connections.open "$SLACK_APP_TOKEN" POST)
  ok=$(printf '%s' "$body" | field ok)
  if [ "$ok" = "True" ] || [ "$ok" = "true" ]; then
    pass "apps.connections.open accepted it — Socket Mode will connect"
  else
    err=$(printf '%s' "$body" | field error)
    case "$err" in
      invalid_auth)  fail "rejected. Regenerate the app-level token; the value is shown once." ;;
      missing_scope) fail "the app-level token lacks connections:write. Regenerate it with that scope." ;;
      "")            fail "no response from Slack. Check egress from this host." ;;
      *)             fail "apps.connections.open returned: $err" ;;
    esac
  fi
fi

# ---- channel ---------------------------------------------------------------------------
if [ -n "$CHANNEL" ] && [ -n "${SLACK_BOT_TOKEN:-}" ]; then
  printf '\nChannel %s\n' "$CHANNEL"
  body=$(slack_call "conversations.info?channel=$CHANNEL" "$SLACK_BOT_TOKEN")
  ok=$(printf '%s' "$body" | field ok)
  if [ "$ok" = "True" ] || [ "$ok" = "true" ]; then
    name=$(printf '%s' "$body" | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["channel"].get("name",""))
except Exception: print("")')
    member=$(printf '%s' "$body" | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["channel"].get("is_member", False))
except Exception: print("")')
    pass "resolves to #$name"
    if [ "$member" = "True" ] || [ "$member" = "true" ]; then
      pass "the bot is already a member"
    else
      warn "the bot is not in this channel. Run /invite @NemoClaw Assistant in #$name,"
      warn "otherwise mentions never reach it and readiness will still report connected."
    fi
  else
    err=$(printf '%s' "$body" | field error)
    case "$err" in
      channel_not_found) fail "not visible to this app. Check the ID, or invite the bot first." ;;
      missing_scope)     warn "cannot verify membership: conversations.info needs channels:read."
                         warn "Apply the current manifest scopes, reinstall the app, and retry." ;;
      "")                fail "no response from Slack. Check egress from this host." ;;
      *)                 fail "conversations.info returned: $err" ;;
    esac
  fi
fi

rm -f /tmp/.slackhdr.$$

printf '\n'
if [ "$FAILED" -gt 0 ]; then
  printf 'Not ready: %d blocking problem(s). Onboarding would not enable Slack.\n\n' "$FAILED"
  exit 1
fi
if [ "$WARNED" -gt 0 ]; then
  printf 'Usable, with %d warning(s) above. Onboarding will accept these tokens.\n\n' "$WARNED"
  exit 0
fi
printf 'Ready. Both tokens validate the way onboarding validates them.\n\n'
