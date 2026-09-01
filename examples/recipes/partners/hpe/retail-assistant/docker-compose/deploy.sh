#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "${COMPOSE_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../../../../.." && pwd)"

# Resolve the example's single dependency contract before Compose interpolates
# and passes the platform values into the workspace container.
# shellcheck disable=SC1091
source "${REPO_ROOT}/scripts/example_dependencies.sh"
load_example_dependencies "$EXAMPLE_DIR"

cd "$COMPOSE_DIR"
exec docker compose "$@"
