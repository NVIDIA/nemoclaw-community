#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"
load_env
require_command openshell

destination="${1:-$EXAMPLE_DIR/.tmp/atif}"
mkdir -p "$destination"
openshell sandbox download "$NEMOCLAW_SANDBOX_NAME" /sandbox/atif "$destination"
echo "ATIF directory downloaded to: $destination (only finalized sessions create files)"
