#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Tear down what bring-up.sh created: sandbox, then host services.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$DIR")"
RUN="$EXAMPLE_DIR/.run"
SANDBOX_NAME="${SANDBOX_NAME:-x402-gate-demo}"

if command -v openshell >/dev/null 2>&1; then
  echo "Deleting sandbox $SANDBOX_NAME (if present)"
  openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
fi
for svc in gate rail; do
  if [ -f "$RUN/$svc.pid" ]; then
    kill "$(cat "$RUN/$svc.pid")" 2>/dev/null || true
    echo "stopped $svc"
  fi
done
rm -rf "$RUN"
echo "tear-down complete."
