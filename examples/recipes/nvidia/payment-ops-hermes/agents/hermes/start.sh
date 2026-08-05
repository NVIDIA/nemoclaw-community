#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-/sandbox/.hermes}"
export HERMES_DISABLE_LAZY_INSTALLS=1
export NEMO_RELAY_GATEWAY_URL="http://127.0.0.1:4040"

child_pids=()
cleanup() {
  for pid in "${child_pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

mkdir -p /sandbox/atif
nemo-relay --bind 127.0.0.1:4040 >>/tmp/nemo-relay.log 2>&1 &
relay_pid=$!
child_pids+=("$relay_pid")

for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:4040/healthz >/dev/null 2>&1 && break
  if ! kill -0 "$relay_pid" 2>/dev/null; then
    echo "NeMo Relay exited during startup" >&2
    tail -n 40 /tmp/nemo-relay.log >&2 || true
    exit 1
  fi
  sleep 0.5
done
curl -fsS http://127.0.0.1:4040/healthz >/dev/null || {
  echo "NeMo Relay did not become healthy" >&2
  tail -n 40 /tmp/nemo-relay.log >&2 || true
  exit 1
}
echo "[nemo-relay] healthy on 127.0.0.1:4040"

hermes gateway run >>/tmp/hermes.log 2>&1 &
hermes_pid=$!
child_pids+=("$hermes_pid")

# Hermes currently binds its API server to loopback. Expose it to the
# OpenShell sandbox interface without widening the Hermes listener itself.
socat TCP-LISTEN:8642,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:18642 &
socat_pid=$!
child_pids+=("$socat_pid")

for _ in $(seq 1 180); do
  curl -fsS http://127.0.0.1:18642/health >/dev/null 2>&1 && break
  if ! kill -0 "$hermes_pid" 2>/dev/null; then
    echo "Hermes exited during startup" >&2
    tail -n 60 /tmp/hermes.log >&2 || true
    exit 1
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:18642/health >/dev/null || {
  echo "Hermes did not become healthy" >&2
  tail -n 60 /tmp/hermes.log >&2 || true
  exit 1
}
echo "[hermes] healthy on 0.0.0.0:8642"

wait "$hermes_pid"
