#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Local contract: a second runtime on shared GPUs may set maxReplicas up to the
# allocatable GPUs, but not above them, and never to a non-integer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hpa-common.sh
source "${SCRIPT_DIR}/hpa-common.sh"

# Stand-in for the node inventory: 8 allocatable GPUs on Ready nodes.
hpa_common_allocatable_gpus() {
  echo 8
}

out="$(hpa_common_verify_shared_gpu_ceiling 8)"
[[ "${out}" == *"maxReplicas=8 on 8 allocatable GPUs"* ]]
hpa_common_verify_shared_gpu_ceiling 1 >/dev/null

for bad in 9 0 -1 abc 08; do
  if hpa_common_verify_shared_gpu_ceiling "${bad}" >/dev/null 2>&1; then
    echo "ERROR: shared GPU ceiling accepted '${bad}' on 8 allocatable GPUs" >&2
    exit 1
  fi
done

echo "OK: shared GPU ceiling allows 1..8 on 8 GPUs and rejects 9, 0, and non-integers"
