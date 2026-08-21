#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# OpenShell v0.0.85 Kubernetes sandboxes intentionally boot with an idle supervisor
# command. Start the NemoClaw image entrypoint as the sandbox identity and keep this
# foreground exec session alive for the duration of the experimental runtime.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../versions.env
source "${CHART_DIR}/versions.env"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v openshell >/dev/null 2>&1 || fail "missing command: openshell"
ACTUAL_OPENSHELL_VERSION="$(openshell --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)"
[[ "${ACTUAL_OPENSHELL_VERSION}" == "${OPENSHELL_VERSION}" ]] \
  || fail "OpenShell CLI ${OPENSHELL_VERSION} is required; found ${ACTUAL_OPENSHELL_VERSION:-unknown}"

SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-nemoclaw-onprem}"
openshell sandbox get "${SANDBOX_NAME}" >/dev/null 2>&1 \
  || fail "sandbox ${SANDBOX_NAME} does not exist; run create-nemoclaw-sandbox.sh first"

echo "Starting NemoClaw/OpenClaw in ${SANDBOX_NAME}. Keep this terminal open."
echo "OpenShell owns the pod sandbox; the NemoClaw entrypoint runs as the sandbox identity."
exec openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- \
  /usr/local/bin/nemoclaw-start
