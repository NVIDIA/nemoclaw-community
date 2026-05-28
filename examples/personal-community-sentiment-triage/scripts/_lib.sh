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

# Auto-source .env if present and key vars are missing. Called by every
# phase script that needs credentials, so a developer can run any one of
# them directly without `set -a && source .env` in the shell first. The
# `Auto-sourcing` echo prints once per process tree (sentinel exported into
# env) so bring-up.sh doesn't print it 3x.
load_env() {
  if [[ -f "$EXAMPLE_DIR/.env" && -z "${OUTLOOK_TENANT_ID:-}${SLACK_BOT_TOKEN:-}" ]]; then
    [[ -z "${_NEMOCLAW_ENV_LOADED:-}" ]] && \
      echo "Auto-sourcing $EXAMPLE_DIR/.env (vars not present in shell)"
    set -a
    # shellcheck disable=SC1091
    . "$EXAMPLE_DIR/.env"
    set +a
    export _NEMOCLAW_ENV_LOADED=1
  fi
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

# Whether the given provider exists with the expected type. Strips ANSI
# escapes that `openshell provider get` emits even when piped.
provider_type_matches() {
  local pname="$1" expected="$2"
  openshell provider get "$pname" 2>/dev/null \
    | sed $'s/\x1b\\[[0-9;]*m//g' \
    | grep -qE "^[[:space:]]*Type:[[:space:]]+$expected[[:space:]]*\$"
}

# Upsert a single credential on a provider. Uses `env -i` to build a clean
# sub-environment, so the value openshell stores is the one we explicitly
# pass — not whatever is leaking in from the parent shell. Without this,
# `openshell provider update --credential X` silently picks up an empty
# value when the caller forgets to `set -a && source .env` first, breaking
# placeholder substitution at the L7 proxy at sandbox-start time.
# If the existing provider has a different type, drop it first — `provider
# update` cannot change a provider's type.
upsert_cred() {
  local pname="$1" ptype="$2" envkey="$3" value="$4"
  if [[ -z "$value" ]]; then
    echo "  skip $pname.$envkey (no value)"
    return 0
  fi
  if openshell provider get "$pname" >/dev/null 2>&1 && ! provider_type_matches "$pname" "$ptype"; then
    echo "  $pname exists with wrong type; recreating as $ptype"
    openshell provider delete "$pname" >/dev/null
  fi
  if openshell provider get "$pname" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" "$envkey=$value" \
      openshell provider update "$pname" --credential "$envkey"
  else
    env -i HOME="$HOME" PATH="$PATH" "$envkey=$value" \
      openshell provider create --name "$pname" --type "$ptype" --credential "$envkey"
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
