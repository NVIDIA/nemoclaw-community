#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Live HPA watch with normalized targets (GPU % or latency ms).
# Prefer this over: kubectl get hpa -n nemoclaw-gpu -w
# (kubectl prints Quantity suffixes like 3k / 3099666m).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/get-hpa.sh" -w "$@"
