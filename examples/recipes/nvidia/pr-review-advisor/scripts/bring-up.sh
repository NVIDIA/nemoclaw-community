#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

ambient_nvidia_set=0
ambient_compatible_set=0
ambient_nvidia=""
ambient_compatible=""
if [[ "${NVIDIA_INFERENCE_API_KEY+x}" == x \
    && -n "${NVIDIA_INFERENCE_API_KEY:-}" ]]; then
  ambient_nvidia_set=1
  ambient_nvidia="$NVIDIA_INFERENCE_API_KEY"
fi
if [[ "${COMPATIBLE_API_KEY+x}" == x && -n "${COMPATIBLE_API_KEY:-}" ]]; then
  ambient_compatible_set=1
  ambient_compatible="$COMPATIBLE_API_KEY"
fi

recover=()
if [[ "${1:-}" == "--recover-error" ]]; then
  recover=(--recover-error)
elif [[ $# -gt 0 ]]; then
  echo "Usage: $(basename "$0") [--recover-error]" >&2
  exit 2
fi

scrub_external_secrets
load_env
scrub_external_secrets
require_command curl
require_command openshell
require_command python3
validate_port "$HERMES_FORWARD_PORT"
acquire_review_lock
trap release_review_lock EXIT INT TERM

echo "═══ Phase 1/4: Dedicated OpenShell gateway ═══"
bash "$DIR/01-gateway.sh" --lock-held
echo "═══ Phase 2/4: Inference provider and exact route ═══"
(
  if [[ "$ambient_nvidia_set" == 1 ]]; then
    export NVIDIA_INFERENCE_API_KEY="$ambient_nvidia"
  fi
  if [[ "$ambient_compatible_set" == 1 ]]; then
    export COMPATIBLE_API_KEY="$ambient_compatible"
  fi
  bash "$DIR/02-provider.sh" --lock-held
)
ambient_nvidia=""
ambient_compatible=""
unset ambient_nvidia ambient_compatible
scrub_external_secrets
echo "═══ Phase 3/4: Hermes review sandbox ═══"
bash "$DIR/03-sandbox.sh" --lock-held "${recover[@]}"
echo "═══ Phase 4/4: Loopback API forward ═══"
assert_sandbox_ready
start_forward

echo "Review advisor ready. Run:"
echo "  bash $DIR/review.sh --repo /path/to/repo --base <sha> --head <sha>"
