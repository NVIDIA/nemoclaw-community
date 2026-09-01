#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "${CHART_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../../../../.." && pwd)"

# Resolve the example's single dependency contract before injecting the
# platform values into the chart.
# shellcheck disable=SC1091
source "${REPO_ROOT}/scripts/example_dependencies.sh"
load_example_dependencies "$EXAMPLE_DIR"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 RELEASE_NAME [helm upgrade --install flags]" >&2
  exit 2
fi

release_name="$1"
shift

exec helm upgrade --install "$release_name" "$CHART_DIR" "$@" \
  --set-string "versions.nemoclawInstallTag=${NEMOCLAW_INSTALL_TAG}" \
  --set-string "versions.nemoclawInstallRef=${NEMOCLAW_INSTALL_REF}" \
  --set-string "versions.nemoclawAgent=${NEMOCLAW_AGENT}" \
  --set-string "versions.openshellVersion=${OPENSHELL_VERSION}"
