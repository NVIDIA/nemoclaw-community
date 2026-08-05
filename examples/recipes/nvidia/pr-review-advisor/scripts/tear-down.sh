#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

destroy=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destroy-sandbox) destroy=1 ;;
    -h|--help) echo "Usage: tear-down.sh [--destroy-sandbox]"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

scrub_external_secrets
load_env
scrub_external_secrets
validate_name "$NEMOCLAW_SANDBOX_NAME"
validate_port "$HERMES_FORWARD_PORT"
acquire_review_lock
trap release_review_lock EXIT INT TERM
if command -v openshell >/dev/null 2>&1; then
  openshell_preflight
  assert_gateway_identity
  run_openshell forward stop "$HERMES_FORWARD_PORT" "$NEMOCLAW_SANDBOX_NAME" \
    >/dev/null 2>&1 || true
fi
if [[ "$destroy" == 1 ]]; then
  require_command openshell
  assert_sandbox_ready
  echo "Destroying $NEMOCLAW_SANDBOX_NAME. Snapshot memory first if it must be retained."
  run_openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME"
fi
echo "Review-advisor forward stopped."
