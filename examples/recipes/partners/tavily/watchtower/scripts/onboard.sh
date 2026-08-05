#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Step 1 of 2: non-interactively onboard an OpenClaw sandbox with Tavily as
# the web-search provider. Scripts THROUGH `nemoclaw onboard`, not around it:
# this script only validates .env, exports the documented non-interactive
# answer variables, and hands off to the wizard with the checked-in agent
# manifest. Onboarding wires the built-in web_search and tavily_extract tools
# to Tavily, stores the key as an OpenShell provider placeholder, applies the
# Tavily egress policy, and bakes in the explicit web_fetch denial.
#
# Idempotent: if the sandbox already exists, prints its status and exits 0.
#
# Try after this script:
#   $ nemoclaw watchtower status
#   $ bash scripts/install.sh

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

if ! command -v nemoclaw >/dev/null; then
  echo "nemoclaw not in PATH — install it first (the acceptance variable must be on the bash side of the pipe):" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash" >&2
  echo "Then open a new terminal (or 'source ~/.bashrc') and re-run this script." >&2
  exit 1
fi

# Web search: Tavily is the point of this example, so it is required.
require_var TAVILY_API_KEY "get a key at https://app.tavily.com"

# Inference: validate the vars the selected provider path needs, per the
# NemoClaw non-interactive onboarding docs.
require_var NEMOCLAW_PROVIDER "e.g. 'build' for NVIDIA Endpoints, 'custom' for an OpenAI-compatible endpoint"
case "$NEMOCLAW_PROVIDER" in
  build)
    require_var NVIDIA_INFERENCE_API_KEY "get a key at https://build.nvidia.com"
    ;;
  custom)
    require_var COMPATIBLE_API_KEY "use any non-empty value if the endpoint needs no auth"
    require_var NEMOCLAW_ENDPOINT_URL "the endpoint must already be serving"
    require_var NEMOCLAW_MODEL "model ID as reported by the server"
    ;;
  *)
    echo "note: NEMOCLAW_PROVIDER=$NEMOCLAW_PROVIDER — this script does not pre-validate that path's credential variables; nemoclaw onboard will." >&2
    ;;
esac

export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_WEB_SEARCH_PROVIDER=tavily
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_SANDBOX_NAME

if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' already exists — nothing to do."
  echo "Inspect it with: nemoclaw $NEMOCLAW_SANDBOX_NAME status"
  exit 0
fi

echo "Onboarding sandbox '$NEMOCLAW_SANDBOX_NAME' (provider: $NEMOCLAW_PROVIDER, web search: tavily)"
run nemoclaw onboard --non-interactive --agents "$EXAMPLE_DIR/agents.yaml"

echo
echo "Onboard complete. Next: bash scripts/install.sh"
