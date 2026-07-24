# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the phase scripts. Source this from each phase script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Find the most recent snapshot tarball, or print nothing if none exist.
# Used by restore.sh when the caller doesn't pass an explicit path.
latest_snapshot() {
  [[ -d "$SNAPSHOT_DIR" ]] || return 0
  ls -1t "$SNAPSHOT_DIR"/*.tar.gz 2>/dev/null | head -1
}

# Auto-source .env if present. Always re-sources on every call so that
# vars added to .env after the operator's last manual `set -a; source .env`
# don't silently stay unset — an "already loaded if these key vars exist"
# heuristic once let a stale shell skip re-sourcing and miss newly-added vars.
# Sourcing is idempotent (set -a + . file).
# The `Auto-sourcing` echo prints once per process tree (sentinel exported
# into env) so bring-up.sh doesn't print it on every phase.
load_env() {
  [[ -f "$EXAMPLE_DIR/.env" ]] || return 0
  [[ -z "${_NEMOCLAW_ENV_LOADED:-}" ]] && \
    echo "Auto-sourcing $EXAMPLE_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  . "$EXAMPLE_DIR/.env"
  set +a
  export _NEMOCLAW_ENV_LOADED=1
}

# Validate messaging-channel config. Fails fast if no channel is configured
# or if Outlook is partially configured (any of the 4 set ⇒ all 4 required).
# Safe to call from multiple phase scripts; the work is cheap.
assert_messaging_config() {
  if [[ -z "${OUTLOOK_CLIENT_ID:-}" && -z "${SLACK_BOT_TOKEN:-}" ]]; then
    echo "No messaging channel configured — set Outlook (OUTLOOK_TENANT_ID + OUTLOOK_CLIENT_ID + OUTLOOK_TARGET_MAILBOX + OUTLOOK_REPLY_TO) or Slack (SLACK_BOT_TOKEN + SLACK_APP_TOKEN) in $EXAMPLE_DIR/.env" >&2
    exit 1
  fi
  local set_=() missing_=()
  for v in OUTLOOK_TENANT_ID OUTLOOK_CLIENT_ID OUTLOOK_TARGET_MAILBOX OUTLOOK_REPLY_TO; do
    if [[ -n "${!v:-}" ]]; then set_+=("$v"); else missing_+=("$v"); fi
  done
  if (( ${#set_[@]} > 0 && ${#missing_[@]} > 0 )); then
    echo "Partial Outlook configuration in $EXAMPLE_DIR/.env" >&2
    echo "  Set:     ${set_[*]}" >&2
    echo "  Missing: ${missing_[*]}" >&2
    echo "Fill all four OUTLOOK_* vars or leave the entire block empty." >&2
    exit 1
  fi
}

# Auto-source .env before deriving any defaults from it.
load_env

# Parse ATIF_RELAY_ENDPOINT into the parts every downstream consumer needs:
# the canonical URL (docker-compose env, bridge upstream, provider profile,
# policy egress rule), the host (TLS cert CN + first SAN), and the port
# (relay bind addr, compose healthcheck). One operator-facing knob, three
# derived forms. Fails fast on a malformed URL so a typo doesn't quietly
# break TLS / sandbox-bridge handshake at runtime.
export ATIF_RELAY_ENDPOINT="${ATIF_RELAY_ENDPOINT:-https://host.openshell.internal:18443}"
{
  _url="$ATIF_RELAY_ENDPOINT"
  _scheme="${_url%%://*}"
  if [[ "$_scheme" != "https" || "$_scheme" == "$_url" ]]; then
    echo "ATIF_RELAY_ENDPOINT must be an https:// URL (got: $ATIF_RELAY_ENDPOINT)" >&2
    exit 1
  fi
  _hostport="${_url#*://}"
  _hostport="${_hostport%%/*}"
  ATIF_RELAY_HOST="${_hostport%%:*}"
  ATIF_RELAY_PORT="${_hostport##*:}"
  if [[ -z "$ATIF_RELAY_HOST" || "$ATIF_RELAY_PORT" == "$ATIF_RELAY_HOST" ]]; then
    echo "ATIF_RELAY_ENDPOINT must include host:port (got: $ATIF_RELAY_ENDPOINT)" >&2
    exit 1
  fi
  if ! [[ "$ATIF_RELAY_PORT" =~ ^[0-9]+$ ]]; then
    echo "ATIF_RELAY_ENDPOINT port must be numeric (got: $ATIF_RELAY_PORT)" >&2
    exit 1
  fi
  export ATIF_RELAY_HOST ATIF_RELAY_PORT
  unset _url _scheme _hostport
}

# Shared, overridable knobs.
SANDBOX_NAME="${SANDBOX_NAME:-hermes-direct}"
GATEWAY_NAME="${OPENSHELL_GATEWAY:-openshell}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-$EXAMPLE_DIR/.snapshots}"

# Resolve the local gateway endpoint for the default installation paths.
default_gateway_endpoint() {
  if [[ -n "${OPENSHELL_GATEWAY_ENDPOINT:-}" ]]; then
    echo "$OPENSHELL_GATEWAY_ENDPOINT"
    return
  fi

  case "$GATEWAY_NAME" in
    openshell)   echo "https://127.0.0.1:17670" ;;
    snap-docker) echo "http://127.0.0.1:17670" ;;
    *)           echo "" ;;
  esac
}

# ATIF export is governed by two orthogonal vars:
#   ATIF_EXPORT_MODE   = local (default) | relay   — deployment-wide: in-sandbox
#                        /tmp/atif vs host-relay export. Gates the sandbox bake,
#                        host services, and providers.
#   ATIF_RELAY_BACKEND = s3 | minio                — the relay's downstream, only
#                        meaningful when mode=relay (see atif_relay_backend).
#
# Returns 0 if export goes through the relay (mode=relay), 1 for local (unset or
# "local"). Exits 1 on any other value so a typo doesn't silently degrade to
# local-only and lose traces.
atif_remote_enabled() {
  case "${ATIF_EXPORT_MODE:-local}" in
    relay)     return 0 ;;
    local)     return 1 ;;
    *) echo "Unknown ATIF_EXPORT_MODE: $ATIF_EXPORT_MODE (expected local|relay)" >&2; exit 1 ;;
  esac
}

# Echo the validated relay downstream backend (s3|minio). Only call when
# atif_remote_enabled is true; exits 1 (loud) if ATIF_RELAY_BACKEND is
# unset/invalid so a misconfigured relay run fails at bring-up rather than
# silently defaulting. Used as the docker-compose profile and the s3-vs-minio
# decision in the host-services/providers scripts.
atif_relay_backend() {
  case "${ATIF_RELAY_BACKEND:-}" in
    s3|minio|s3-compatible) echo "$ATIF_RELAY_BACKEND" ;;
    "") echo "ATIF_EXPORT_MODE=relay requires ATIF_RELAY_BACKEND (s3|minio|s3-compatible) to be set in $EXAMPLE_DIR/.env" >&2; exit 1 ;;
    *)  echo "Unknown ATIF_RELAY_BACKEND: $ATIF_RELAY_BACKEND (expected s3|minio|s3-compatible)" >&2; exit 1 ;;
  esac
}

# Echo the validated relay downstream bucket for the given (already-validated)
# backend. minio defaults to the dev bucket; s3 / s3-compatible REQUIRE an
# explicit ATIF_RELAY_BUCKET and fail loud here at bring-up if it's unset
# (the dev default would otherwise silently target a wrong real bucket).
atif_relay_bucket() {
  local backend="$1"
  case "$backend" in
    minio) echo "${ATIF_RELAY_BUCKET:-nemo-relay-traces}" ;;
    s3|s3-compatible)
      if [[ -z "${ATIF_RELAY_BUCKET:-}" ]]; then
        echo "ATIF_RELAY_BACKEND=$backend requires ATIF_RELAY_BUCKET (the real downstream bucket) to be set in $EXAMPLE_DIR/.env" >&2
        exit 1
      fi
      echo "$ATIF_RELAY_BUCKET" ;;
  esac
}

# The per-VM relay bearer is a generated secret, NOT operator config — so it
# lives in the gitignored .bootstrap/cache/ (like the Outlook refresh token),
# never in .env. Generate-once-then-reuse: callers do
#   export ATIF_RELAY_AUTH_TOKEN="${ATIF_RELAY_AUTH_TOKEN:-$(atif_relay_token)}"
# before bringing up the relay / registering the OpenShell provider, so both
# read the SAME value. An operator may still set ATIF_RELAY_AUTH_TOKEN in .env
# to override. Rotate by deleting the cache file (+ .registered) and re-running.
ATIF_RELAY_TOKEN_CACHE="$EXAMPLE_DIR/.bootstrap/cache/atif-relay-token"
atif_relay_token() {
  if [[ ! -s "$ATIF_RELAY_TOKEN_CACHE" ]]; then
    mkdir -p "$(dirname "$ATIF_RELAY_TOKEN_CACHE")"
    ( umask 077; printf 'atif-%s\n' "$(openssl rand -hex 24)" > "$ATIF_RELAY_TOKEN_CACHE" )
  fi
  cat "$ATIF_RELAY_TOKEN_CACHE"
}

# Whether the given provider exists with the expected type. Strips ANSI
# escapes that `openshell provider get` emits even when piped.
provider_type_matches() {
  local pname="$1" expected="$2"
  openshell provider get "$pname" 2>/dev/null \
    | sed $'s/\x1b\\[[0-9;]*m//g' \
    | grep -qE "^[[:space:]]*Type:[[:space:]]+$expected[[:space:]]*\$"
}

# Upsert one or more credentials on a provider. Trailing args are
# `KEY=value` pairs. Uses `env -i` to build a clean sub-environment, so
# the values openshell stores are the ones we explicitly pass — not
# whatever leaks in from the parent shell. Without this, `openshell
# provider update --credential X` silently picks up an empty value when
# the caller forgets to `set -a && source .env` first, breaking
# placeholder substitution at the L7 proxy at sandbox-start time.
#
# If the existing provider has a different type, drop it first —
# `provider update` cannot change a provider's type.
#
# Usage:
#   upsert_cred my-provider my-type FOO_TOKEN="$FOO_TOKEN"
#   upsert_cred my-provider my-type FOO_TOKEN="$FOO" BAR_TOKEN="$BAR"
upsert_cred() {
  local pname="$1" ptype="$2"
  shift 2
  local env_args=() cred_args=() pair
  for pair in "$@"; do
    env_args+=("$pair")
    cred_args+=(--credential "${pair%%=*}")
  done
  if openshell provider get "$pname" >/dev/null 2>&1 && ! provider_type_matches "$pname" "$ptype"; then
    echo "  $pname exists with wrong type; recreating as $ptype"
    openshell provider delete "$pname" >/dev/null
  fi
  if openshell provider get "$pname" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider update "$pname" "${cred_args[@]}"
  else
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider create --name "$pname" --type "$ptype" "${cred_args[@]}"
  fi
}

# Fail unless $SANDBOX_NAME shows up in `openshell sandbox list` with status
# "Ready". Used by snapshot/restore/download-traces, all of which need a
# running sandbox.
assert_sandbox_ready() {
  if ! openshell sandbox list 2>/dev/null | grep -E "^\s*$SANDBOX_NAME\s" | grep -qi ready; then
    echo "Sandbox $SANDBOX_NAME is not ready — bring it up first (scripts/bring-up.sh)" >&2
    exit 1
  fi
}

# `openshell sandbox download <sb> /sandbox/X <work>/` may land at
# $work/X/... or $work/... depending on OpenShell's basename handling.
# Echo whichever it produced.
resolve_download_root() {
  local work="$1" basename_="$2"
  if [[ -d "$work/$basename_" ]]; then
    echo "$work/$basename_"
  else
    echo "$work"
  fi
}

# Walk $1 deleting files whose names match a conservative credential-shape
# allowlist. Populates the global EXCLUDED_FILES array with relative paths
# (relative to $1) and prints them to stderr. Used by snapshot.sh and
# download-traces.sh before tar-ing up their respective payloads.
filter_credential_files() {
  local root="$1"
  EXCLUDED_FILES=()
  while IFS= read -r -d '' f; do
    EXCLUDED_FILES+=("${f#"$root/"}")
    rm -f "$f"
  done < <(find "$root" -type f \( \
      -iname '.env' -o -iname '*.env' -o \
      -iname '*secret*' -o -iname '*token*' -o \
      -iname 'auth-profiles*' -o -iname 'credentials*' -o \
      -iname 'id_rsa*' -o -iname '*.pem' -o -iname '*.key' \
    \) -print0)
  if (( ${#EXCLUDED_FILES[@]} > 0 )); then
    echo "Excluded ${#EXCLUDED_FILES[@]} credential-shaped file(s):" >&2
    printf '  %s\n' "${EXCLUDED_FILES[@]}" >&2
  fi
}

# Write the companion manifest JSON for a tarball produced by snapshot.sh or
# download-traces.sh. Trailing positional args are the excluded file list
# (relative paths from the source root); leave empty if filter_credential_files
# excluded nothing. `--empty-note "<text>"` overrides the default "filter
# applied" note for the case where the source dir was empty (atif).
write_snapshot_manifest() {
  local tarball="$1" manifest="$2" ts="$3" sandbox="$4" source_path="$5" empty_note="$6"
  shift 6
  local file_count tarball_size
  file_count=$(tar tzf "$tarball" | wc -l)
  tarball_size=$(stat -c '%s' "$tarball")
  python3 "$EXAMPLE_DIR/scripts/lib/write-manifest.py" \
    --tarball "$tarball" --output "$manifest" --ts "$ts" --sandbox "$sandbox" \
    --source-path "$source_path" --file-count "$file_count" \
    --tarball-bytes "$tarball_size" --empty-note "$empty_note" \
    "$@"
}
