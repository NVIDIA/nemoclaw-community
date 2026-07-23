#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

export PATH="/usr/local/bin:/opt/hermes/.venv/bin:/usr/bin:/bin"
export HERMES_HOME="${HERMES_HOME:-/sandbox/.hermes}"
export HERMES_DISABLE_LAZY_INSTALLS=1

runtime_fingerprint="${REVIEW_ADVISOR_RUNTIME_FINGERPRINT:-}"
fingerprint_file=/opt/review-advisor/runtime-fingerprint
if [[ ! "$runtime_fingerprint" =~ ^[0-9a-f]{64}$ \
    || ! -f "$fingerprint_file" \
    || "$(<"$fingerprint_file")" != "$runtime_fingerprint" ]]; then
  echo "Review advisor runtime fingerprint is missing or inconsistent" >&2
  exit 1
fi

api_key="${REVIEW_ADVISOR_API_KEY:-}"
if [[ ! "$api_key" =~ ^[A-Za-z0-9_-]{32,128}$ ]]; then
  echo "REVIEW_ADVISOR_API_KEY must be a 32-128 character URL-safe value" >&2
  exit 1
fi
public_port="${REVIEW_ADVISOR_PUBLIC_PORT:-8642}"
if [[ ! "$public_port" =~ ^[0-9]+$ ]] \
  || ((10#$public_port < 1024 || 10#$public_port > 65535 || 10#$public_port == 18642)); then
  echo "REVIEW_ADVISOR_PUBLIC_PORT must be 1024-65535 and not 18642" >&2
  exit 1
fi

umask 077
{
  printf 'API_SERVER_PORT=18642\n'
  printf 'API_SERVER_HOST=127.0.0.1\n'
  printf 'API_SERVER_KEY=%s\n' "$api_key"
} >"$HERMES_HOME/.env"

child_pids=()
# shellcheck disable=SC2329
cleanup() {
  local pid
  for pid in "${child_pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

hermes gateway run >>/tmp/hermes.log 2>&1 &
hermes_pid=$!
child_pids+=("$hermes_pid")

# Hermes v0.18 binds the API listener to loopback. Expose only the sandbox
# transport port; the host lifecycle creates a loopback-only OpenShell forward.
socat "TCP-LISTEN:${public_port},fork,reuseaddr,bind=0.0.0.0" TCP:127.0.0.1:18642 \
  >>/tmp/socat.log 2>&1 &
socat_pid=$!
child_pids+=("$socat_pid")

for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:18642/health >/dev/null 2>&1; then
    echo "[review-advisor] Hermes ready on sandbox port ${public_port}"
    wait "$hermes_pid"
    exit $?
  fi
  if ! kill -0 "$hermes_pid" 2>/dev/null; then
    echo "Hermes exited during startup" >&2
    tail -n 100 /tmp/hermes.log >&2 || true
    exit 1
  fi
  sleep 1
done

echo "Hermes did not become healthy" >&2
tail -n 100 /tmp/hermes.log >&2 || true
exit 1
