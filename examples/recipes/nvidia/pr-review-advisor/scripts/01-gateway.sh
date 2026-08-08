#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

lock_held=0
if [[ "${1:-}" == "--lock-held" ]]; then
  lock_held=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $(basename "$0") [--lock-held]" >&2
  exit 2
fi

scrub_external_secrets
load_env
scrub_external_secrets
require_command openshell
validate_name "$OPENSHELL_GATEWAY"

if [[ "$lock_held" == 1 ]]; then
  [[ "${REVIEW_ADVISOR_LOCK_DIR:-}" == "${STATE_DIR}/review.lock" \
      && -d "$REVIEW_ADVISOR_LOCK_DIR" ]] || {
    echo "--lock-held requires the inherited lifecycle lock" >&2
    exit 2
  }
else
  acquire_review_lock
  trap release_review_lock EXIT INT TERM
fi

set +e
gateway_registration_exists
registration_status=$?
set -e
case "$registration_status" in
  0) ;;
  1)
    run_openshell_unbound gateway add "$OPENSHELL_GATEWAY_ENDPOINT" \
      --local --name "$OPENSHELL_GATEWAY"
    ;;
  *)
    echo "Could not inspect the OpenShell gateway registry" >&2
    exit 1
    ;;
esac

assert_gateway_identity
run_openshell status >/dev/null || {
  echo "OpenShell gateway is not reachable: $OPENSHELL_GATEWAY" >&2
  exit 1
}
echo "OpenShell gateway ready: $OPENSHELL_GATEWAY"
