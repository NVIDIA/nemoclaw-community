# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for every lib/*.sh module. Sourced by ./swarm; not executable.

# ── Output ───────────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_GREEN=$'\e[32m'; C_YEL=$'\e[33m'; C_RED=$'\e[31m'; C_DIM=$'\e[2m'; C_BOLD=$'\e[1m'; C_OFF=$'\e[0m'
else
  C_GREEN=""; C_YEL=""; C_RED=""; C_DIM=""; C_BOLD=""; C_OFF=""
fi

log()  { printf '%s▸ %s%s\n' "$C_BOLD" "$*" "$C_OFF"; }
ok()   { printf '  %sok%s   %s\n' "$C_GREEN" "$C_OFF" "$*"; }
# Everything goes to stdout, on purpose: agents' terminal tools and humans'
# `| tee` both see one stream, and a `die` reason never gets lost in a
# separately captured stderr (which is exactly how a bot creation once "exited
# 1 with no error").
warn() { printf '  %swarn%s %s\n' "$C_YEL" "$C_OFF" "$*"; }
fail() { printf '  %sFAIL%s %s\n' "$C_RED" "$C_OFF" "$*"; }
dim()  { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }
die()  { fail "$*"; exit 1; }

# ── Strings ──────────────────────────────────────────────────────────────────
# openshell prints ANSI colour codes; strip them BEFORE comparing or awk-ing.
strip_ansi() { sed -r 's/\x1B\[[0-9;]*[mK]//g'; }

valid_name() { [[ "$1" =~ ^[a-z][a-z0-9-]{0,30}$ ]]; }

# Escape an arbitrary literal for use inside an extended regular expression.
# Sandbox prefixes are operator-configurable, so process-match patterns must
# never interpret their punctuation as regex syntax.
ere_escape() { printf '%s' "$1" | sed 's/[][(){}.^$*+?|\\]/\\&/g'; }

# ── Requirements ─────────────────────────────────────────────────────────────
require_cmd() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "missing command: $c"
  done
}

# Read a secret from a file, insisting on sane permissions. Prints the value.
read_secret() {
  local f="$1"
  [[ -f "$f" ]] || die "secret file not found: $f"
  local mode
  mode=$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f")
  [[ "$mode" =~ ^[0-7]?[0-7]00$ ]] || die "secret file $f must be mode 600 (is $mode): chmod 600 $f"
  local v
  v=$(tr -d '\r\n' < "$f")
  [[ -n "$v" ]] || die "secret file $f is empty"
  printf '%s' "$v"
}

# Retry a command N times with a fixed sleep. retry 5 3 curl ...
retry() {
  local n="$1" pause="$2"; shift 2
  local i
  for ((i = 1; i <= n; i++)); do
    "$@" && return 0
    (( i < n )) && sleep "$pause"
  done
  return 1
}

# HTTP status of a URL, or 000. http_code URL [curl args...]
http_code() {
  local url="$1"; shift
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" "$url" 2>/dev/null || echo 000
}

# Run something detached from this shell so it survives the SSH session that
# started it. Logs to $2. daemonize LOGFILE cmd args...
daemonize() {
  local logf="$1"; shift
  mkdir -p "$(dirname "$logf")"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" > "$logf" 2>&1 < /dev/null &
  else
    # macOS has no setsid; nohup + disown is enough to outlive this shell.
    nohup "$@" > "$logf" 2>&1 < /dev/null &
    disown 2>/dev/null || true
  fi
}

# Delete lines matching a pattern in place; GNU and BSD sed differ on -i.
sed_delete() { # sed_delete PATTERN FILE
  local tmp; tmp=$(mktemp "${2}.XXXXXX")
  grep -v -- "$1" "$2" > "$tmp" || true
  chmod --reference="$2" "$tmp" 2>/dev/null || chmod 600 "$tmp"
  mv "$tmp" "$2"
}

# Kill every process whose full command line matches the pattern. Quiet.
pkill_pattern() { pkill -f -- "$1" 2>/dev/null || true; }

# ── State ────────────────────────────────────────────────────────────────────
state_init() {
  local owner="$SWARM_STATE/owner-token" tmp token
  mkdir -p "$SWARM_STATE"/{keys,policies,logs,relay,souls,owned}
  chmod 700 "$SWARM_STATE" "$SWARM_STATE/keys" "$SWARM_STATE/souls" "$SWARM_STATE/owned"
  [[ ! -e "$owner" || ( -f "$owner" && ! -L "$owner" ) ]] \
    || die "$owner must be a regular, non-symlink file"

  # One stable, deployment-scoped identity owns every resource made from this
  # state directory.  A hard-link publishes it atomically, so two concurrent
  # invocations cannot silently choose different identities.
  if [[ ! -s "$owner" ]]; then
    token=$(openssl rand -hex 32)
    tmp="$SWARM_STATE/.owner-token.$$.$RANDOM"
    (umask 077; printf '%s\n' "$token" > "$tmp")
    ln "$tmp" "$owner" 2>/dev/null || true
    rm -f "$tmp"
  fi
  chmod 600 "$owner"
  token=$(tr -d '\r\n' < "$owner")
  [[ "$token" =~ ^[0-9a-f]{64}$ ]] || die "$owner is not a valid deployment owner token; refusing to manage resources"
}

deployment_owner_token() { tr -d '\r\n' < "$SWARM_STATE/owner-token"; }

# ── Portability (Linux hosts and macOS with Colima or Docker Desktop) ────────
# GNU base64 wraps at 76 columns unless told -w0; macOS base64 has no -w.
b64() { base64 < "${1:-/dev/stdin}" | tr -d '\n'; }
# Is anything listening on TCP port $1 on this host?
port_in_use() {
  if command -v ss >/dev/null 2>&1; then ss -lnt 2>/dev/null | grep -q ":$1 "
  else lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; fi
}
# Best-guess address someone else would SSH to. Empty on a laptop is fine.
host_reach_addr() {
  if command -v hostname >/dev/null 2>&1 && hostname -I >/dev/null 2>&1; then
    hostname -I | tr ' ' '\n' | grep -vE '^(127\.|169\.254\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[01]\.)' | head -1
  else
    ipconfig getifaddr en0 2>/dev/null || true
  fi
}
is_macos() { [[ "$(uname -s)" == Darwin ]]; }
# First 16 hex of a file's SHA-256; coreutils or macOS shasum.
sha16() { { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | cut -c1-16; }
# Octal permission bits of a file (600), GNU or BSD stat.
file_mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null; }
# macOS has no `timeout` unless coreutils is installed as gtimeout.
if ! command -v timeout >/dev/null 2>&1 && command -v gtimeout >/dev/null 2>&1; then
  timeout() { gtimeout "$@"; }
fi

bot_key_file()  { printf '%s/keys/%s.key' "$SWARM_STATE" "$1"; }
bot_port_file() { printf '%s/keys/%s.port' "$SWARM_STATE" "$1"; }
bot_state_soul_file() { printf '%s/souls/%s.md' "$SWARM_STATE" "$1"; }
bot_log()       { printf '%s/logs/%s-%s.log' "$SWARM_STATE" "$1" "$2"; }
sandbox_of()    { printf '%s%s' "$SANDBOX_PREFIX" "$1"; }
