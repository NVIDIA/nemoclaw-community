#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

recover_error=0
lock_held=0
allow_quarantine=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recover-error) recover_error=1 ;;
    --lock-held) lock_held=1 ;;
    --allow-quarantine) allow_quarantine=1 ;;
    *)
      echo "Usage: $(basename "$0") [--recover-error] [--lock-held] [--allow-quarantine]" >&2
      exit 2
      ;;
  esac
  shift
done

scrub_external_secrets
load_env
require_command openshell
require_command python3
load_runtime_dependencies
validate_name "$NEMOCLAW_SANDBOX_NAME"
validate_port "$HERMES_FORWARD_PORT"

owns_lock=0
staged=""
create_pid=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$create_pid" ]] && kill -0 "$create_pid" 2>/dev/null; then
    kill -TERM -- "-$create_pid" 2>/dev/null || true
    wait "$create_pid" 2>/dev/null || true
  fi
  [[ -z "$staged" ]] || rm -f -- "$staged" "${staged}.bak"
  [[ "$owns_lock" == 0 ]] || release_review_lock
  exit "$status"
}

if [[ "$lock_held" == 1 ]]; then
  [[ "${REVIEW_ADVISOR_LOCK_DIR:-}" == "${STATE_DIR}/review.lock" \
      && -d "$REVIEW_ADVISOR_LOCK_DIR" ]] || {
    echo "--lock-held requires the inherited lifecycle lock" >&2
    exit 2
  }
else
  acquire_review_lock
  owns_lock=1
fi
if [[ "$allow_quarantine" == 1 ]]; then
  [[ "$lock_held" == 1 ]] || {
    echo "--allow-quarantine requires --lock-held" >&2
    exit 2
  }
  assert_quarantine_recovery_context
else
  assert_sandbox_not_quarantined
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ensure_api_key
local_api_key="$REVIEW_ADVISOR_API_KEY"
unset REVIEW_ADVISOR_API_KEY
scrub_external_secrets

assert_gateway_identity
phase="$(sandbox_phase)"
case "${phase,,}" in
  ready)
    # A name match is insufficient: never reuse or delete a sandbox whose
    # baked repository/install/model/assets identity differs from this install.
    assert_runtime_fingerprint
    if [[ "$allow_quarantine" == 0 ]] \
      && run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      curl -fsS --max-time 3 http://127.0.0.1:18642/health >/dev/null 2>&1; then
      run_openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" \
        --wait "$NEMOCLAW_SANDBOX_NAME"
      echo "Reusing healthy sandbox: $NEMOCLAW_SANDBOX_NAME"
      exit 0
    fi
    [[ "$recover_error" == 1 || "$allow_quarantine" == 1 ]] || {
      echo "Sandbox is Ready but Hermes is unhealthy; inspect it or rerun with --recover-error" >&2
      exit 1
    }
    ;;
  error)
    [[ "$recover_error" == 1 || "$allow_quarantine" == 1 ]] || {
      echo "Sandbox is in Error; inspect it or rerun with --recover-error" >&2
      exit 1
    }
    ;;
  missing)
    ;;
  *)
    echo "Sandbox is transitioning (phase: $phase); wait and retry" >&2
    exit 1
    ;;
esac

if [[ "${phase,,}" != "missing" ]]; then
  run_openshell forward stop "$HERMES_FORWARD_PORT" "$NEMOCLAW_SANDBOX_NAME" \
    >/dev/null 2>&1 || true
  run_openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME"
  for _ in $(seq 1 60); do
    [[ "$(sandbox_phase)" == "Missing" ]] && break
    sleep 1
  done
  [[ "$(sandbox_phase)" == "Missing" ]] || {
    echo "Sandbox deletion did not complete" >&2
    exit 1
  }
fi

compute_runtime_fingerprint
staged="$EXAMPLE_DIR/.Dockerfile.staged.${REVIEW_ADVISOR_INSTALL_ID}"
[[ ! -L "$staged" && ( ! -e "$staged" || -f "$staged" ) ]] || {
  echo "Refusing unsafe staged Dockerfile path: $staged" >&2
  exit 1
}
cp "$EXAMPLE_DIR/agents/hermes/Dockerfile" "$staged"
chmod 600 "$staged"
sed -i.bak \
  -e "s|^ARG BASE_IMAGE=.*|ARG BASE_IMAGE=$NEMOCLAW_BASE_IMAGE|" \
  -e "s|^ARG HERMES_VERSION=.*|ARG HERMES_VERSION=$HERMES_VERSION|" \
  -e "s|^ARG NEMOCLAW_MODEL=.*|ARG NEMOCLAW_MODEL=$NEMOCLAW_MODEL|" \
  -e "s|^ARG REVIEW_ADVISOR_RUNTIME_FINGERPRINT=.*|ARG REVIEW_ADVISOR_RUNTIME_FINGERPRINT=$REVIEW_ADVISOR_RUNTIME_FINGERPRINT|" \
  "$staged"
rm -f "${staged}.bak"

echo "Building review-advisor sandbox..."
run_openshell_detached sandbox create \
  --from "$staged" \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  --policy "$EXAMPLE_DIR/policy.yaml" \
  -- env "REVIEW_ADVISOR_API_KEY=$local_api_key" \
    "REVIEW_ADVISOR_PUBLIC_PORT=$HERMES_FORWARD_PORT" review-advisor-start \
  </dev/null &
create_pid=$!

ready=0
for _ in $(seq 1 240); do
  if [[ "$(sandbox_phase)" == "Ready" ]]; then
    ready=1
    break
  fi
  if ! kill -0 "$create_pid" 2>/dev/null; then
    wait "$create_pid" || true
    create_pid=""
    echo "Sandbox creation exited before Ready" >&2
    exit 1
  fi
  sleep 2
done

workload_ready=0
if [[ "$ready" == 1 ]]; then
  assert_runtime_fingerprint
  for _ in $(seq 1 180); do
    if run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      curl -fsS --max-time 3 http://127.0.0.1:18642/health >/dev/null 2>&1; then
      workload_ready=1
      break
    fi
    kill -0 "$create_pid" 2>/dev/null || break
    sleep 1
  done
fi

kill -TERM -- "-$create_pid" 2>/dev/null || true
wait "$create_pid" 2>/dev/null || true
create_pid=""
[[ "$ready" == 1 && "$workload_ready" == 1 ]] || {
  echo "Review-advisor sandbox did not become healthy" >&2
  run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    tail -n 120 /tmp/hermes.log 2>/dev/null || true
  exit 1
}

assert_runtime_fingerprint
run_openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" \
  --wait "$NEMOCLAW_SANDBOX_NAME"
echo "Sandbox ready: $NEMOCLAW_SANDBOX_NAME"
