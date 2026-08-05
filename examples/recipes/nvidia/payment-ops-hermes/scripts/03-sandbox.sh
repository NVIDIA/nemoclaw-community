#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

recover_error=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recover-error) recover_error=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--recover-error]"
      echo "  --recover-error  replace an unhealthy or Error-state sandbox"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

load_env
require_command openshell

staged="$EXAMPLE_DIR/.Dockerfile.staged"
trap 'rm -f "$staged"' EXIT
cp "$EXAMPLE_DIR/agents/hermes/Dockerfile" "$staged"

model="${NEMOCLAW_MODEL:-${FINANCE_MODEL:-nvidia/nemotron-3-super-120b-a12b}}"
project="${NEMO_RELAY_PROJECT_NAME:-finguard-payment-ops}"
endpoint="${PHOENIX_COLLECTOR_ENDPOINT:-http://host.openshell.internal:6006/v1/traces}"
sed -i \
  -e "s|^ARG NEMOCLAW_MODEL=.*|ARG NEMOCLAW_MODEL=$model|" \
  -e "s|^ARG NEMO_RELAY_PROJECT_NAME=.*|ARG NEMO_RELAY_PROJECT_NAME=\"$project\"|" \
  -e "s|^ARG PHOENIX_COLLECTOR_ENDPOINT=.*|ARG PHOENIX_COLLECTOR_ENDPOINT=\"$endpoint\"|" \
  "$staged"

phase="$(sandbox_phase)"
case "${phase,,}" in
  missing)
    ;;
  ready)
    if sandbox_workload_healthy; then
      echo "Reusing healthy sandbox: $NEMOCLAW_SANDBOX_NAME"
      openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$NEMOCLAW_SANDBOX_NAME"
      echo "Sandbox ready: $NEMOCLAW_SANDBOX_NAME (Relay + Hermes healthy)"
      exit 0
    fi
    if [[ "$recover_error" != 1 ]]; then
      echo "Sandbox $NEMOCLAW_SANDBOX_NAME is Ready, but Relay or Hermes is unhealthy." >&2
      echo "Inspect it before recovery, or run:" >&2
      echo "  bash scripts/bring-up.sh --recover-error" >&2
      exit 1
    fi
    echo "Replacing unhealthy sandbox: $NEMOCLAW_SANDBOX_NAME"
    openshell forward stop 8642 "$NEMOCLAW_SANDBOX_NAME" >/dev/null 2>&1 || true
    openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME"
    for _ in $(seq 1 30); do
      [[ "$(sandbox_phase)" == "Missing" ]] && break
      sleep 1
    done
    [[ "$(sandbox_phase)" == "Missing" ]] || {
      echo "Sandbox deletion did not complete: $NEMOCLAW_SANDBOX_NAME" >&2
      exit 1
    }
    ;;
  error)
    if [[ "$recover_error" != 1 ]]; then
      echo "Sandbox $NEMOCLAW_SANDBOX_NAME is in Error state." >&2
      echo "Its image and configuration are preserved, but OpenShell cannot execute or forward to it." >&2
      echo "To replace only this failed sandbox using cached image layers, run:" >&2
      echo "  bash scripts/bring-up.sh --recover-error" >&2
      exit 1
    fi
    echo "Replacing failed sandbox: $NEMOCLAW_SANDBOX_NAME"
    openshell forward stop 8642 "$NEMOCLAW_SANDBOX_NAME" >/dev/null 2>&1 || true
    openshell sandbox delete "$NEMOCLAW_SANDBOX_NAME"
    for _ in $(seq 1 30); do
      [[ "$(sandbox_phase)" == "Missing" ]] && break
      sleep 1
    done
    [[ "$(sandbox_phase)" == "Missing" ]] || {
      echo "Sandbox deletion did not complete: $NEMOCLAW_SANDBOX_NAME" >&2
      exit 1
    }
    ;;
  *)
    echo "Sandbox $NEMOCLAW_SANDBOX_NAME is currently in phase '$phase'." >&2
    echo "Wait for that transition to finish, then rerun bash scripts/bring-up.sh." >&2
    exit 1
    ;;
esac

echo "Building and creating sandbox $NEMOCLAW_SANDBOX_NAME..."
setsid openshell sandbox create \
  --from "$staged" \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  --policy "$EXAMPLE_DIR/policy.yaml" \
  -- env nemoclaw-start </dev/null &
create_pid=$!

ready=0
for _ in $(seq 1 240); do
  if openshell sandbox list 2>/dev/null | grep -E "^\s*$NEMOCLAW_SANDBOX_NAME\s" | grep -qi ready; then
    ready=1
    break
  fi
  kill -0 "$create_pid" 2>/dev/null || {
    wait "$create_pid" || true
    echo "Sandbox creation exited before reaching ready" >&2
    exit 1
  }
  sleep 2
done

if [[ "$ready" == 1 ]]; then
  echo "Sandbox infrastructure ready; waiting for NeMo Relay and Hermes..."
  workload_ready=0
  for _ in $(seq 1 180); do
    if openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
         curl -fsS http://127.0.0.1:4040/healthz >/dev/null 2>&1 \
       && openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
         curl -fsS http://127.0.0.1:18642/health >/dev/null 2>&1; then
      workload_ready=1
      break
    fi
    if ! kill -0 "$create_pid" 2>/dev/null; then
      break
    fi
    sleep 1
  done
else
  workload_ready=0
fi

kill -TERM -- -"$create_pid" 2>/dev/null || true
wait "$create_pid" 2>/dev/null || true
[[ "$ready" == 1 ]] || { echo "Sandbox did not reach ready in 8 minutes" >&2; exit 1; }
if [[ "$workload_ready" != 1 ]]; then
  echo "Sandbox workload did not become healthy." >&2
  openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    tail -80 /tmp/nemo-relay.log 2>/dev/null || true
  openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    tail -120 /tmp/hermes.log 2>/dev/null || true
  exit 1
fi

openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$NEMOCLAW_SANDBOX_NAME"
echo "Sandbox ready: $NEMOCLAW_SANDBOX_NAME (Relay + Hermes healthy)"
