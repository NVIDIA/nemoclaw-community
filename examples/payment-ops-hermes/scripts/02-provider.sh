#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
require_command openshell

if ! openshell settings get --global 2>/dev/null | grep -qE 'providers_v2_enabled\s*=\s*true'; then
  echo "Provider v2 is disabled. Run:" >&2
  echo "  openshell settings set --global --key providers_v2_enabled --value true --yes" >&2
  exit 1
fi

key="${COMPATIBLE_API_KEY:-${NVIDIA_API_KEY:-}}"
[[ -n "$key" ]] || {
  echo "Set COMPATIBLE_API_KEY (or NVIDIA_API_KEY) in .env" >&2
  exit 1
}

provider="${INFERENCE_PROVIDER_NAME:-payment-ops-inference}"
base_url="${NEMOCLAW_ENDPOINT_URL:-${FINANCE_API_URL:-https://integrate.api.nvidia.com/v1}}"
model="${NEMOCLAW_MODEL:-${FINANCE_MODEL:-nvidia/nemotron-3-super-120b-a12b}}"

if openshell provider get "$provider" >/dev/null 2>&1; then
  env NVIDIA_API_KEY="$key" openshell provider update "$provider" \
    --credential NVIDIA_API_KEY --config "NVIDIA_BASE_URL=$base_url"
else
  env NVIDIA_API_KEY="$key" openshell provider create --name "$provider" --type nvidia \
    --credential NVIDIA_API_KEY --config "NVIDIA_BASE_URL=$base_url"
fi
openshell inference set --no-verify --provider "$provider" --model "$model"
echo "Inference ready: provider=$provider model=$model"
