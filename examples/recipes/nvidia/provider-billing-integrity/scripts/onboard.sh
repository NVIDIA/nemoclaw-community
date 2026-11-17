#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Create the provider-billing-integrity sandbox non-interactively with the
# OpenClaw harness (default) or, with NEMOCLAW_AGENT=hermes, the Hermes harness.
# NVIDIA Endpoints is the default inference provider. Web
# search is disabled: the skill works only from the data it ships. The sandbox
# is CPU-only by default, so GPU passthrough is turned off. For the optional CUDA-X
# path set NEMOCLAW_SANDBOX_GPU=1 (and optionally NEMOCLAW_SANDBOX_GPU_DEVICE, a GPU
# index, UUID or CDI name such as nvidia.com/gpu=0) to enable direct GPU access.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

if ! command -v nemoclaw >/dev/null; then
  echo "nemoclaw not in PATH — install it first:" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash" >&2
  echo "Then open a new terminal (or source your shell profile) and rerun this script." >&2
  exit 1
fi

NEMOCLAW_PROVIDER="${NEMOCLAW_PROVIDER:-build}"
NEMOCLAW_MODEL="${NEMOCLAW_MODEL:-nvidia/nemotron-3.5-lightning-30b-a3b}"

case "$NEMOCLAW_PROVIDER" in
  build)
    require_var NVIDIA_INFERENCE_API_KEY "get a key at https://build.nvidia.com"
    ;;
  custom)
    require_var COMPATIBLE_API_KEY "use any non-empty value if the endpoint needs no authentication"
    require_var NEMOCLAW_ENDPOINT_URL "the endpoint must already be serving"
    ;;
  *)
    echo "note: NEMOCLAW_PROVIDER=$NEMOCLAW_PROVIDER — nemoclaw onboard will validate this provider's credentials." >&2
    ;;
esac

export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_AGENT
export NEMOCLAW_PROVIDER
export NEMOCLAW_MODEL
export NEMOCLAW_SANDBOX_NAME
export NEMOCLAW_WEB_SEARCH_PROVIDER=none

if sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' already exists — nothing to do."
  echo "Inspect it with: nemoclaw $NEMOCLAW_SANDBOX_NAME status"
  exit 0
fi

GPU_FLAGS=(--no-sandbox-gpu)
if [[ "${NEMOCLAW_SANDBOX_GPU:-0}" == "1" ]]; then
  GPU_FLAGS=(--sandbox-gpu)
  [[ -z "${NEMOCLAW_SANDBOX_GPU_DEVICE:-}" ]] || GPU_FLAGS+=(--sandbox-gpu-device "$NEMOCLAW_SANDBOX_GPU_DEVICE")
fi

echo "Onboarding sandbox '$NEMOCLAW_SANDBOX_NAME'"
echo "  harness: $NEMOCLAW_AGENT"
echo "  inference: $NEMOCLAW_PROVIDER ($NEMOCLAW_MODEL)"
echo "  sandbox GPU: ${GPU_FLAGS[*]}"
run nemoclaw onboard \
  --non-interactive \
  --yes \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  "${GPU_FLAGS[@]}" \
  --agent "$NEMOCLAW_AGENT" \
  --yes-i-accept-third-party-software

echo
echo "Onboarding complete. Next: bash scripts/install.sh"
