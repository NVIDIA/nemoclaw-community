#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Approve Slack pairing requests without leaving the host.
#
# With the Slack user allowlist empty, an unlisted sender gets a pairing code instead of
# silence, and the bot tells them to ask the owner to run 'openclaw pairing approve slack CODE'
# verbatim. That command lives inside the sandbox, so the owner cannot run it as
# printed — it has to go through 'openshell sandbox exec'. This wraps that, adds a temporary
# watch mode, and strips the runtime banner so the output is readable.
#
#   ./scripts/slack-pair.sh list
#   ./scripts/slack-pair.sh approve 3YMY3SN9
#   ./scripts/slack-pair.sh watch --for 900
#
# Nothing here is a security boundary. Watch mode approves every request it sees, and everyone
# it admits shares one sandbox, one inference API key, and one egress path. Run it for a
# temporary pairing window, not as a service.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

SANDBOX=${SANDBOX:-$NEMOCLAW_SANDBOX_NAME}
CHANNEL=slack
INTERVAL=10
DURATION=900
ASSUME_YES=0
RAW=0

usage() {
  cat <<'EOF'
Usage: slack-pair.sh <command> [options]

Commands:
  list                 Show pending pairing requests
  approve CODE [CODE]  Approve one or more pairing codes
  watch                Poll for requests and approve them as they arrive

Options:
  --sandbox NAME   Sandbox to talk to (default: configured sandbox name)
  --interval N     Seconds between polls in watch mode (default: 10)
  --for N          Stop watching after N seconds (default: 900)
  --yes            Watch mode: approve without asking. Implied by a non-interactive shell.
  --raw            list: print the runtime's own output, banner and all
  -h, --help       Show this help

Watch mode approves everyone who asks. Your Slack workspace is the only access boundary
in front of it.
EOF
}

CMD=${1:-}
[ $# -gt 0 ] && shift
case "$CMD" in
  -h|--help|"") usage; exit 0 ;;
esac

CODES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --sandbox)  SANDBOX=${2:-}; shift 2 ;;
    --interval) INTERVAL=${2:-}; shift 2 ;;
    --for)      DURATION=${2:-}; shift 2 ;;
    --yes)      ASSUME_YES=1; shift ;;
    --raw)      RAW=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    -*)         printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 3 ;;
    *)          CODES+=("$1"); shift ;;
  esac
done

command -v openshell >/dev/null 2>&1 || {
  printf 'openshell is not on PATH. Try: export PATH="$HOME/.local/bin:$PATH"\n' >&2
  printf 'This needs openshell rather than nemoclaw: pairing codes are only reachable\n' >&2
  printf 'through "openshell sandbox exec". The nemoclaw installer puts both in place.\n' >&2
  exit 3
}
[ -t 0 ] || ASSUME_YES=1

ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
info() { printf '  \033[36m·\033[0m     %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
err()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }

# The runtime prints a version banner, a rotating joke, and node's proxy-agent warning around
# every command. Drop all of it so the signal is visible.
clean() {
  sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' \
      -e '/UNDICI-EHPA/d' \
      -e '/trace-warnings/d' \
      -e '/^OpenClaw [0-9]/d' \
      -e '/^All your chats/d' \
      -e '/^Docs: docs\.openclaw\.ai/d' \
      -e '/^[[:space:]]*[│◇◆○●][[:space:]]*$/d' \
    | sed -e '/^[[:space:]]*$/d'
}

pairing() {
  openshell sandbox exec --name "$SANDBOX" -- openclaw pairing "$@" 2>&1
}

# A code is eight uppercase alphanumerics. The banner and the joke line are mixed case, so
# this does not collide with them, but print what was matched before acting on it.
extract_codes() {
  grep -oE '\b[A-Z0-9]{8}\b' | sort -u
}

cmd_list() {
  local out
  out=$(pairing list --channel "$CHANNEL")
  if [ "$RAW" = 1 ]; then
    printf '%s\n' "$out"
    return 0
  fi
  local body
  body=$(printf '%s\n' "$out" | clean)
  if [ -z "$body" ]; then
    info "no pending pairing requests"
    return 0
  fi
  printf '%s\n' "$body"
}

cmd_approve() {
  local code rc=0
  for code in "$@"; do
    local out
    out=$(pairing approve "$CHANNEL" "$code")
    if printf '%s' "$out" | grep -qi 'approved'; then
      ok "$code — $(printf '%s\n' "$out" | clean | grep -i 'approved' | head -1)"
      # The first approval on a fresh bot also claims command ownership. Say so.
      if printf '%s' "$out" | grep -qi 'ownerAllowFrom was empty'; then
        warn "this approval also made that user the command owner"
      fi
    else
      err "$code — not approved"
      printf '%s\n' "$out" | clean | sed 's/^/        /'
      rc=1
    fi
  done
  return $rc
}

cmd_watch() {
  local deadline=$(( $(date +%s) + DURATION ))
  local seen=" "
  printf '\nWatching %s for Slack pairing requests, every %ss, for %ss.\n' \
    "$SANDBOX" "$INTERVAL" "$DURATION"
  printf 'Everyone who asks gets approved. Ctrl-C to stop.\n\n'

  while [ "$(date +%s)" -lt "$deadline" ]; do
    local codes
    codes=$(pairing list --channel "$CHANNEL" | clean | extract_codes)
    for code in $codes; do
      case "$seen" in *" $code "*) continue ;; esac
      seen="$seen$code "
      printf '[%s] pairing request %s\n' "$(date +%H:%M:%S)" "$code"
      if [ "$ASSUME_YES" = 0 ]; then
        printf '        approve? [Y/n]: '
        read -r reply </dev/tty
        case "$reply" in [Nn]*) info "skipped"; continue ;; esac
      fi
      cmd_approve "$code"
    done
    sleep "$INTERVAL"
  done

  printf '\nStopped after %ss. Re-run to keep approving.\n\n' "$DURATION"
}

case "$CMD" in
  list)
    printf '\nPending pairing requests on %s\n\n' "$SANDBOX"
    cmd_list
    printf '\n'
    ;;
  approve)
    if [ "${#CODES[@]}" -eq 0 ]; then
      printf 'approve needs at least one code. Get them from: slack-pair.sh list\n' >&2
      exit 3
    fi
    printf '\n'
    cmd_approve "${CODES[@]}"
    printf '\n'
    ;;
  watch)
    cmd_watch
    ;;
  *)
    printf 'Unknown command: %s\n\n' "$CMD" >&2
    usage >&2
    exit 3
    ;;
esac
