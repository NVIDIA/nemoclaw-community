#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Verifier entry point. Metric scripts each write /logs/verifier/metric_<name>.json,
# then merge_metrics.py folds them into the single reward.json Harbor reads.
set -euo pipefail
mkdir -p /logs/verifier
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$SCRIPT_DIR/check_iou.py"
python3 "$SCRIPT_DIR/merge_metrics.py"
