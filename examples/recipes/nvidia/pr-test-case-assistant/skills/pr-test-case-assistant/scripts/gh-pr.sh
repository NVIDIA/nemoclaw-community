#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Fetch public pull request data through one validated path.
#
# Repository coordinates arrive from a Slack message, so they are untrusted
# input. This script validates them against GitHub's naming rules before any
# URL is built, which keeps request-supplied text out of command construction.
# Response bodies are printed as data and are never evaluated.
#
#   gh-pr.sh list  <owner/name>
#   gh-pr.sh meta  <owner/name> <number>
#   gh-pr.sh files <owner/name> <number>
#
# A repository URL is accepted in place of owner/name. Exit status is 0 on
# success, 2 for rejected input, 3 for a GitHub rate-limit response, and 4 for
# a transport or API error.

set -euo pipefail

readonly API="https://api.github.com"
readonly MAX_BYTES=200000
readonly USER_AGENT="nemoclaw-pr-test-case-assistant"

# The files endpoint returns at most 100 entries per page. Read a bounded number of
# pages so a large pull request cannot exhaust the public quota, and report the
# shortfall rather than letting a partial diff look complete.
readonly PER_PAGE=100
readonly MAX_FILE_PAGES=5

OWNER=""
NAME=""
URL_NUMBER=""

die() {
  printf 'gh-pr: %s\n' "$1" >&2
  exit "${2:-2}"
}

usage() {
  cat <<'EOF'
Usage:
  gh-pr.sh list  <owner/name>
  gh-pr.sh meta  <owner/name> <number>
  gh-pr.sh files <owner/name> <number>

Accepts owner/name or a repository URL. Validates coordinates before any
request. Prints GitHub data as text; never executes it.
EOF
}

# Reduce a URL or owner/name pair to its parts without interpreting the value.
normalize_coordinates() {
  local rest="$1"
  rest="${rest#https://}"
  rest="${rest#http://}"
  rest="${rest#www.}"
  rest="${rest#api.github.com/repos/}"
  rest="${rest#github.com/}"
  rest="${rest%/}"
  rest="${rest%.git}"

  if [[ "$rest" =~ ^([^/]+)/([^/]+)/pulls?/([0-9]+)$ ]]; then
    OWNER="${BASH_REMATCH[1]}"
    NAME="${BASH_REMATCH[2]}"
    URL_NUMBER="${BASH_REMATCH[3]}"
  elif [[ "$rest" =~ ^([^/]+)/([^/]+)$ ]]; then
    OWNER="${BASH_REMATCH[1]}"
    NAME="${BASH_REMATCH[2]}"
  else
    die "expected owner/name or a repository URL, got: $1"
  fi
}

# The allowed character sets exclude every shell metacharacter, path
# separator, and whitespace character, so a rejected value never reaches curl.
validate_coordinates() {
  [[ "$OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] \
    || die "owner is not a valid GitHub account name: $OWNER"
  [[ "$OWNER" == *- ]] && die "owner must not end with a hyphen: $OWNER"

  [[ "$NAME" =~ ^[A-Za-z0-9._-]{1,100}$ ]] \
    || die "repository is not a valid GitHub repository name: $NAME"
  [[ "$NAME" == "." || "$NAME" == ".." ]] \
    && die "repository name must not be a path segment: $NAME"

  return 0
}

validate_number() {
  local number="$1"
  [[ "$number" =~ ^[1-9][0-9]{0,6}$ ]] \
    || die "pull request number must be a positive integer: $number"
  printf '%s' "$number"
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required inside the sandbox" 4
}

# Print the response body. Truncation is reported so a caller never mistakes a
# cut-off body for a complete one.
fetch() {
  local path="$1" accept="${2:-application/vnd.github+json}" body=""
  local url="$API$path"

  if ! body=$(curl -sS \
    --max-time 30 \
    -H "Accept: $accept" \
    -H "User-Agent: $USER_AGENT" \
    --url "$url" 2>&1); then
    die "request failed: $body" 4
  fi

  case "$body" in
    *'API rate limit exceeded'*|*'secondary rate limit'*)
      die "GitHub rate limit reached. Report this once and stop." 3
      ;;
    *'"message": "Not Found"'*)
      die "GitHub returned Not Found for $path" 4
      ;;
  esac

  if (( ${#body} > MAX_BYTES )); then
    printf '%s\n' "${body:0:MAX_BYTES}"
    printf '\n[truncated at %d bytes; treat this body as incomplete]\n' "$MAX_BYTES" >&2
  else
    printf '%s\n' "$body"
  fi
}

cmd_list() {
  fetch "/repos/$OWNER/$NAME/pulls?state=open&sort=updated&direction=desc&per_page=5" \
    | jq -r '.[] | "#\(.number)\t\(.title)\t\(.user.login)\t\(.updated_at[0:10])"'
}

cmd_meta() {
  local number="$1"
  fetch "/repos/$OWNER/$NAME/pulls/$number" \
    | jq -r '"#\(.number) \(.title)\nby \(.user.login), \(.changed_files) files, +\(.additions)/-\(.deletions)\n\n\(.body // "(no description)")"'
}

# Read changed files across a bounded number of pages and end with an explicit
# coverage line. The count is compared with the metadata's changed_files value,
# so a pull request wider than the page budget is reported as partial instead of
# being presented as the whole diff.
cmd_files() {
  local number="$1"
  local page=1 read_count=0 page_count=0 expected="" body=""

  expected=$(fetch "/repos/$OWNER/$NAME/pulls/$number" | jq -r '.changed_files // empty')

  while (( page <= MAX_FILE_PAGES )); do
    body=$(fetch "/repos/$OWNER/$NAME/pulls/$number/files?per_page=$PER_PAGE&page=$page")
    page_count=$(printf '%s' "$body" | jq 'if type == "array" then length else 0 end')

    (( page_count == 0 )) && break

    printf '%s' "$body" \
      | jq -r '.[] | "=== \(.filename) (+\(.additions)/-\(.deletions))\n\(.patch // "(patch unavailable)")"'

    read_count=$(( read_count + page_count ))
    (( page_count < PER_PAGE )) && break
    page=$(( page + 1 ))
  done

  report_coverage "$read_count" "$expected"
}

# A caller must be able to tell a complete diff from a truncated one without
# counting the output itself.
report_coverage() {
  local read_count="$1" expected="$2"

  if [[ -z "$expected" ]]; then
    printf '\n=== coverage: %d changed files read; the total could not be confirmed.\n' "$read_count"
    printf 'Treat patch coverage as unconfirmed and say so.\n'
    return 0
  fi

  if (( read_count < expected )); then
    printf '\n=== coverage: INCOMPLETE — %d of %d changed files read.\n' "$read_count" "$expected"
    printf 'The remaining %d files were not fetched. State that patch coverage is\n' \
      "$(( expected - read_count ))"
    printf 'partial, and do not claim the full diff was reviewed.\n'
    return 0
  fi

  printf '\n=== coverage: complete — %d of %d changed files read.\n' "$read_count" "$expected"
}

main() {
  local command="${1:-}"
  case "$command" in
    -h|--help|"") usage; exit 0 ;;
  esac
  shift

  [[ $# -ge 1 ]] || die "$command needs a repository"
  require_tool curl
  require_tool jq

  normalize_coordinates "$1"
  validate_coordinates
  shift

  local number=""
  case "$command" in
    list)
      [[ $# -eq 0 ]] || die "list takes only a repository"
      cmd_list
      ;;
    meta|files)
      number="${1:-$URL_NUMBER}"
      [[ -n "$number" ]] || die "$command needs a pull request number"
      number=$(validate_number "$number")
      [[ $# -le 1 ]] || die "$command takes a repository and one number"
      "cmd_$command" "$number"
      ;;
    *)
      die "unknown command: $command"
      ;;
  esac
}

main "$@"
