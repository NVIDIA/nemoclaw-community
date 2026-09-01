#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 1 of 2: import the Shrike v2 provider profile, create the provider
# instance (which holds the key on the gateway), and onboard an OpenClaw
# sandbox scoped to Shrike's enforce plane.
#
# Secret handling — the point of this script: the profile (providers/shrike.yaml)
# declares SHRIKE_API_KEY as a bearer credential with egress scoped to
# api.shrikesecurity.com (enforcement: enforce). `openshell provider create`
# supplies the real key to the GATEWAY once, via a clean env (see upsert_cred).
# The sandboxed agent + hook only ever reference the placeholder
# `openshell:resolve:env:SHRIKE_API_KEY`; the L7 proxy substitutes the real
# value on egress. The raw key never enters the sandbox.
#
# Idempotent: safe to re-run. If the sandbox already exists it re-imports the
# profile / refreshes the provider credential and exits 0.
#
# Try after this script:
#   $ bash scripts/install.sh
#   $ bash scripts/verify.sh

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_dependencies
if ! command -v nemoclaw >/dev/null; then
  echo "nemoclaw not in PATH — install the exact tested stack first:" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh \\" >&2
  echo "    | NEMOCLAW_INSTALL_REF=$NEMOCLAW_INSTALL_REF \\" >&2
  echo "      NEMOCLAW_INSTALL_TAG=$NEMOCLAW_INSTALL_TAG \\" >&2
  echo "      NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash" >&2
  echo "Then open a new terminal (or 'source ~/.bashrc') and re-run this script." >&2
  exit 1
fi
command -v openshell >/dev/null || { echo "openshell not in PATH — is the gateway installed?" >&2; exit 1; }
require_nemoclaw_contract

# Shrike governance: the key is required to obtain enforce verdicts.
require_var SHRIKE_API_KEY "get a key at https://shrikesecurity.com/signup"

# Inference: validate the vars the selected provider path needs.
require_var NEMOCLAW_PROVIDER "e.g. 'build' for NVIDIA Endpoints, 'custom' for an OpenAI-compatible endpoint"
case "$NEMOCLAW_PROVIDER" in
  build)   require_var NVIDIA_INFERENCE_API_KEY "get a key at https://build.nvidia.com" ;;
  custom)
    require_var COMPATIBLE_API_KEY "use any non-empty value if the endpoint needs no auth"
    require_var NEMOCLAW_ENDPOINT_URL "the endpoint must already be serving"
    require_var NEMOCLAW_MODEL "model ID as reported by the server"
    ;;
  *) echo "note: NEMOCLAW_PROVIDER=$NEMOCLAW_PROVIDER — nemoclaw onboard will validate that path's credentials." >&2 ;;
esac

# Provider v2 must be enabled at gateway-global scope for profile import.
if ! openshell settings get --global 2>/dev/null | grep -qE "providers_v2_enabled\s*=\s*true"; then
  echo "providers_v2_enabled is not set at gateway-global scope. Enable it once with:" >&2
  echo "  openshell settings set --global --key providers_v2_enabled --value true --yes" >&2
  exit 1
fi

# 1) Import the Shrike provider profile. Delete-then-import so edits land on a
#    re-run; tolerate the "already exists" case (profile attached to a live
#    sandbox cannot be re-imported and does not need to be).
echo "Importing Shrike provider profile '$SHRIKE_PROFILE_ID' from providers/shrike.yaml"
openshell provider profile delete "$SHRIKE_PROFILE_ID" >/dev/null 2>&1 || true
if ! import_out="$(openshell provider profile import --file "$EXAMPLE_DIR/providers/shrike.yaml" 2>&1)"; then
  if grep -qi "already exists" <<<"$import_out"; then
    echo "  profile already registered (attached to a sandbox; not re-imported)"
  else
    printf '%s\n' "$import_out" >&2
    exit 1
  fi
fi

# 2) Create/refresh the provider instance holding the key on the gateway. The
#    key is passed via a clean env; the sandbox only ever sees the placeholder.
echo "Upserting Shrike provider '$SHRIKE_PROVIDER_NAME' (credential: SHRIKE_API_KEY, held gateway-side)"
upsert_cred "$SHRIKE_PROVIDER_NAME" "$SHRIKE_PROFILE_ID" "SHRIKE_API_KEY=$SHRIKE_API_KEY"

# 3) Onboard the sandbox with the checked-in agent manifest.
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_AGENT
export NEMOCLAW_SANDBOX_NAME
if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  require_openclaw_contract "$NEMOCLAW_SANDBOX_NAME"
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' already exists — profile + provider refreshed above."
  # Ensure the provider is attached even on a re-run (idempotent).
  attach_provider
  echo "Inspect it with: nemoclaw $NEMOCLAW_SANDBOX_NAME status"
  exit 0
fi

case "$INSTALL_MODE" in
  runtime)
    echo "Onboarding sandbox '$NEMOCLAW_SANDBOX_NAME' (provider: $NEMOCLAW_PROVIDER, install mode: runtime)"
    run nemoclaw onboard --non-interactive --agents "$EXAMPLE_DIR/agents.yaml"
    ;;
  image)
    # Durable path: bake the plugin into a version-matched custom sandbox image.
    # build-image.sh prepares the build context and runs `nemoclaw onboard --from`.
    echo "Onboarding sandbox '$NEMOCLAW_SANDBOX_NAME' with a baked plugin image (install mode: image)"
    run bash "$DIR/build-image.sh"
    ;;
  *)
    echo "error: unknown INSTALL_MODE='$INSTALL_MODE' (expected 'runtime' or 'image')" >&2
    exit 1
    ;;
esac

# 4) Attach the Shrike provider to the sandbox so the L7 proxy resolves the
#    key placeholder on egress. Without this the plugin's enforce call cannot
#    authenticate and (being fail-closed) would block every governed action.
attach_provider

echo
if [[ "$INSTALL_MODE" == "image" ]]; then
  echo "Onboard complete (plugin baked into the image). Verify with: bash scripts/verify.sh"
else
  echo "Onboard complete. Next: bash scripts/install.sh"
fi
