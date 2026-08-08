# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the shrike-security scripts. Source this from each script.
# Not meant to run on its own — no shebang.

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Auto-source .env if present. Idempotent (set -a + . file), re-sourced on
# every call so a var added to .env after a stale shell export is not missed.
load_env() {
  [[ -f "$EXAMPLE_DIR/.env" ]] || return 0
  echo "Auto-sourcing $EXAMPLE_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  . "$EXAMPLE_DIR/.env"
  set +a
}

# Fail loud if the named variable is unset or empty. Second arg is an
# optional hint appended to the error message.
require_var() {
  local name="$1" hint="${2:-}"
  if [[ -z "${!name:-}" ]]; then
    echo "error: $name is not set — set it in $EXAMPLE_DIR/.env${hint:+ ($hint)}" >&2
    exit 1
  fi
}

# Print a command, then run it.
run() {
  echo "+ $*"
  "$@"
}

# True if the named sandbox exists on the gateway. Checked via
# `openshell sandbox list --names` (machine-readable, one name per line)
# rather than `nemoclaw <name> status`, whose exit code also reflects
# unrelated status-display failures.
sandbox_exists() {
  command -v openshell >/dev/null || return 1
  openshell sandbox list --names 2>/dev/null | grep -Fxq "$1"
}

load_env

# Upsert a provider instance from an imported profile, supplying the credential
# value via a clean sub-environment (env -i) so openshell stores exactly the
# value we pass — not whatever leaks in from the parent shell. Mirrors the
# convention in the nvidia recipes. `provider update` cannot change a
# provider's type, so drop-and-recreate on a type mismatch.
#
# Usage: upsert_cred <provider-name> <profile-id> KEY="$VALUE"
upsert_cred() {
  local pname="$1" ptype="$2"
  shift 2
  local env_args=() cred_args=() pair
  for pair in "$@"; do
    env_args+=("$pair")
    cred_args+=(--credential "${pair%%=*}")
  done
  if openshell provider get "$pname" >/dev/null 2>&1; then
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider update "$pname" "${cred_args[@]}"
  else
    env -i HOME="$HOME" PATH="$PATH" "${env_args[@]}" \
      openshell provider create --name "$pname" --type "$ptype" "${cred_args[@]}"
  fi
}

# Shared, overridable knobs.
#   NEMOCLAW_SANDBOX_NAME     — sandbox onboard/install/verify address.
#   SHRIKE_PROFILE_ID         — v2 provider-profile id (providers/shrike.yaml).
#   SHRIKE_PROVIDER_NAME      — provider instance created from that profile.
# The provider holds the Shrike key on the gateway; the sandbox env carries
# only the placeholder `openshell:resolve:env:SHRIKE_API_KEY`, substituted by
# the L7 proxy on egress. The real key never enters the sandbox.
NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-shrike-security}"
SHRIKE_PROFILE_ID="${SHRIKE_PROFILE_ID:-nemoclaw-shrike}"
SHRIKE_PROVIDER_NAME="${SHRIKE_PROVIDER_NAME:-${NEMOCLAW_SANDBOX_NAME}-shrike}"

# Governance is delivered as an OpenClaw `before_tool_call` plugin (plugin/),
# NOT a Claude-style PreToolUse settings.json hook (the OpenClaw runtime does
# not load those). Two install paths, selected by INSTALL_MODE:
#
#   runtime  (default, tested)  Build the plugin on the host, stage it into the
#            live sandbox, and `openclaw plugins install` + `enable` +
#            gateway restart. Fast; NOT durable across `nemoclaw <sb> rebuild`.
#
#   image    (durable)          Bake the plugin into a version-matched custom
#            sandbox image at onboard time via `nemoclaw onboard --from`
#            (scripts/build-image.sh). Survives rebuild; provenance-guarded on
#            NemoClaw >= v0.0.76. Heavier: needs a matched NemoClaw source
#            checkout as the Docker build context.
# Default to the supported, durable image path; runtime is an explicit
# dev-only opt-in (INSTALL_MODE=runtime).
INSTALL_MODE="${INSTALL_MODE:-image}"

# Plugin identity + on-host source. SHRIKE_PLUGIN_ID must match the `id` field
# in plugin/openclaw.plugin.json.
SHRIKE_PLUGIN_ID="${SHRIKE_PLUGIN_ID:-shrike-security}"
PLUGIN_DIR="$EXAMPLE_DIR/plugin"
# Stage the plugin OUTSIDE the managed extensions dir, then install FROM here.
# Never copy into /sandbox/.openclaw/extensions/<id> and `--link` — the OpenClaw
# install contract requires staging elsewhere and using a local `plugins install`.
PLUGIN_STAGE_DIR="${PLUGIN_STAGE_DIR:-/sandbox/shrike-plugin-stage}"

# Build the plugin's dist/ from source. Idempotent; needs Node + npm on the host.
build_plugin() {
  command -v npm >/dev/null || { echo "error: npm not in PATH — needed to build the plugin" >&2; return 1; }
  echo "Building the Shrike plugin (npm ci + tsc) in $PLUGIN_DIR"
  ( cd "$PLUGIN_DIR" && npm ci --no-audit --no-fund && npm run build )
  [[ -f "$PLUGIN_DIR/dist/index.js" ]] || { echo "error: build produced no dist/index.js" >&2; return 1; }
}

# Run a command inside the sandbox.
sb_exec() { openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- "$@"; }

# Run the in-sandbox `openclaw` CLI with HOME=/sandbox (its config root).
sb_openclaw() { sb_exec env HOME=/sandbox openclaw "$@"; }

# Restart the sandbox agent gateway so plugin config changes take effect.
restart_gateway() { run nemoclaw "$NEMOCLAW_SANDBOX_NAME" gateway restart --quiet; }

# Paths of the managed config integrity guard inside the sandbox.
OPENCLAW_JSON="/sandbox/.openclaw/openclaw.json"
OPENCLAW_CONFIG_HASH="/sandbox/.openclaw/.config-hash"

# Re-bless the managed config hash after an INTENTIONAL runtime plugin change.
# Enabling a plugin at runtime rewrites openclaw.json out-of-band; the managed
# runtime hashes that file (.config-hash) and refuses to restart on a mismatch
# (GATEWAY_UNSAFE_CONFIG_PATH). Refreshing the hash tells it "this change was on
# purpose."
#
# SECURITY NOTE: .config-hash is a sha256 — it proves INTEGRITY (unchanged since
# last blessed), NOT AUTHENTICITY (who blessed it). This refresh carries no
# signature; it is an operator-asserted, trust-on-first-use action for DEV /
# quick-try installs only. For production, use INSTALL_MODE=image, where the
# change + re-bless happen at trusted build time under NemoClaw's provenance
# guard (a real trusted-source check). See scripts/build-image.sh and the README.
# Write .config-hash per the managed config-integrity contract EXACTLY: a
# bare-filename sha256 computed from inside the config dir (an absolute path in
# the file is rejected by the shield), owned sandbox:sandbox, mode 660 (the same
# ritual the custom-image Dockerfile performs). A truncating '>' preserves perms,
# so the chown/chmod are defensive and match the documented contract. Quiet.
write_config_hash() {
  sb_exec bash -lc 'cd /sandbox/.openclaw \
    && sha256sum openclaw.json > .config-hash \
    && chown sandbox:sandbox .config-hash \
    && chmod 660 .config-hash'
}

rebless_config() {
  echo "  !! Re-blessing the managed config hash (UNSIGNED, operator-asserted)." >&2
  echo "     Refreshing $OPENCLAW_CONFIG_HASH to accept the intended plugin-enable." >&2
  write_config_hash
}

# Restart the gateway, handling the managed integrity guard WITHOUT silently
# bypassing it. On a runtime plugin-enable the restart trips
# GATEWAY_UNSAFE_CONFIG_PATH; we re-bless ONLY when the operator explicitly
# opts in via SHRIKE_RUNTIME_REBLESS=1, otherwise we fail loud and point to the
# production (image) path.
restart_gateway_guarded() {
  local out rc
  out="$(nemoclaw "$NEMOCLAW_SANDBOX_NAME" gateway restart --quiet 2>&1)" && rc=0 || rc=$?
  if (( rc == 0 )); then
    echo "+ gateway restarted"
    return 0
  fi
  if grep -q 'GATEWAY_UNSAFE_CONFIG_PATH' <<<"$out"; then
    if [[ "${SHRIKE_RUNTIME_REBLESS:-}" == "1" ]]; then
      echo "  gateway restart tripped the managed config integrity guard — re-blessing (opt-in set)." >&2
      rebless_config
      # The managed config normalizer rewrites openclaw.json asynchronously, so a
      # single re-bless can race and the hash goes stale before restart. Re-hash
      # and retry a few times until the restart is accepted.
      local attempt
      for attempt in 1 2 3 4 5 6 7 8; do
        if nemoclaw "$NEMOCLAW_SANDBOX_NAME" gateway restart --quiet >/dev/null 2>&1; then
          echo "+ gateway restarted (re-blessed, attempt $attempt)"
          return 0
        fi
        # Let the managed normalizer settle, then re-hash the current file. The
        # race is inherent; this path is best-effort. INSTALL_MODE=image is the
        # deterministic install and does not touch the running config at all.
        sleep 3
        write_config_hash
      done
      echo "error: gateway restart still guarded after re-bless retries — the managed" >&2
      echo "       config normalizer kept changing openclaw.json. Use the reliable" >&2
      echo "       production path instead: INSTALL_MODE=image bash scripts/onboard.sh" >&2
      return 1
    fi
    cat >&2 <<EOF
error: gateway restart was blocked by the managed config integrity guard
       (GATEWAY_UNSAFE_CONFIG_PATH). Enabling the plugin at runtime changed
       openclaw.json; the managed runtime will not restart until that change is
       re-blessed. This recipe does NOT bypass the guard silently.

  DEV / quick-try — re-run with an explicit opt-in to refresh the integrity
  hash (proves intent, NOT authenticity — the refresh is unsigned):
      SHRIKE_RUNTIME_REBLESS=1 bash scripts/install.sh

  PRODUCTION (recommended) — bake + re-bless at trusted build time under
  NemoClaw's provenance guard:
      INSTALL_MODE=image bash scripts/onboard.sh
EOF
    return 1
  fi
  printf '%s\n' "$out" >&2
  return 1
}

# True if the Shrike provider is attached to the sandbox.
provider_attached() {
  openshell sandbox provider list "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null \
    | grep -Fq "$SHRIKE_PROVIDER_NAME"
}

# Attach the gateway-side Shrike provider to the sandbox so the L7 proxy
# resolves `openshell:resolve:env:SHRIKE_API_KEY` on egress. Idempotent.
attach_provider() {
  if provider_attached; then
    echo "Provider '$SHRIKE_PROVIDER_NAME' already attached to '$NEMOCLAW_SANDBOX_NAME'."
    return 0
  fi
  echo "Attaching provider '$SHRIKE_PROVIDER_NAME' to sandbox '$NEMOCLAW_SANDBOX_NAME'"
  run openshell sandbox provider attach "$NEMOCLAW_SANDBOX_NAME" "$SHRIKE_PROVIDER_NAME"
}

# Emit the plugin's runtime inspect JSON with any non-JSON preamble stripped.
# An in-sandbox `exec` can prepend a "[proxy] routing ..." line to stdout, which
# would break a JSON parser; keep only from the first line that opens the object.
plugin_inspect_json() {
  sb_openclaw plugins inspect "$SHRIKE_PLUGIN_ID" --runtime --json 2>/dev/null \
    | awk '/^[[:space:]]*\{/{f=1} f'
}

# True if the plugin reports loaded at runtime (status=loaded, hook registered).
plugin_loaded() {
  plugin_inspect_json | grep -Eq '"status"[[:space:]]*:[[:space:]]*"loaded"'
}
