#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Install the optional auto-heal services for the current user. Run this only
# after scripts/bring-up.sh has created a healthy sandbox.

set -euo pipefail
AUTOHEAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$AUTOHEAL_DIR/lib.sh"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/nemoclaw-autoheal"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
RUNTIME_ENV="$CONFIG_DIR/runtime.env"
TEMPLATE_DIR="$AUTOHEAL_DIR/systemd"
CHECK_ONLY=false

usage() {
  cat <<'EOF'
Usage: bash scripts/autoheal/install.sh [--check]

  --check  Validate first-time setup prerequisites without installing services.

The installer creates user-level systemd services. For a headless host, enable
linger once so they survive logout: sudo loginctl enable-linger "$USER"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

failures=0
check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS  %s\n' "$label"
  else
    printf 'FAIL  %s\n' "$label" >&2
    failures=$((failures + 1))
  fi
}

check "Python 3 is available" command -v python3
check "curl is available" command -v curl
check "Docker is available" command -v docker
check "OpenShell CLI is available" command -v openshell
check "systemd user manager is available" systemctl --user show-environment
check "example .env exists" test -f "$EXAMPLE_DIR/.env"
check "Docker daemon is reachable" docker info
check "sandbox ${AUTOHEAL_SANDBOX_NAME} is Ready" sandbox_ready
check "sandbox gateway is healthy" sandbox_gateway_ok

if [[ "${NEMOCLAW_ENDPOINT_URL:-}" == "http://host.openshell.internal:${AUTOHEAL_PROXY_PORT}"* ]]; then
  if proxy_is_configured; then
    printf 'PASS  configured host TLS proxy upstream\n'
  else
    printf 'FAIL  NEMOCLAW_HOST_TLS_PROXY_UPSTREAM is required when NEMOCLAW_ENDPOINT_URL uses host.openshell.internal:%s\n' "$AUTOHEAL_PROXY_PORT" >&2
    failures=$((failures + 1))
  fi
fi

if (( failures > 0 )); then
  printf '\nFix the failed checks before installing auto-heal.\n' >&2
  exit 1
fi

if "$CHECK_ONLY"; then
  printf '\nAll checks passed. Run this script without --check to install auto-heal.\n'
  exit 0
fi

mkdir -p "$CONFIG_DIR" "$UNIT_DIR"
umask 077
cat >"$RUNTIME_ENV" <<EOF
EXAMPLE_DIR=$EXAMPLE_DIR
SANDBOX_NAME=$AUTOHEAL_SANDBOX_NAME
NEMOCLAW_HOST_TLS_PROXY_UPSTREAM=$AUTOHEAL_PROXY_UPSTREAM
NEMOCLAW_HOST_TLS_PROXY_PORT=$AUTOHEAL_PROXY_PORT
EOF
chmod 600 "$RUNTIME_ENV"

render_unit() {
  local template="$1" destination="$2" escaped_dir escaped_env
  escaped_dir="$(printf '%s' "$EXAMPLE_DIR" | sed 's/[&|]/\\&/g')"
  escaped_env="$(printf '%s' "$RUNTIME_ENV" | sed 's/[&|]/\\&/g')"
  sed -e "s|@EXAMPLE_DIR@|$escaped_dir|g" -e "s|@RUNTIME_ENV@|$escaped_env|g" \
    "$TEMPLATE_DIR/$template" >"$UNIT_DIR/$destination"
}

render_unit nemoclaw-hermes-gateway-forward.service.in nemoclaw-hermes-gateway-forward.service
render_unit nemoclaw-hermes-watchdog.service.in nemoclaw-hermes-watchdog.service
render_unit nemoclaw-hermes-watchdog.timer.in nemoclaw-hermes-watchdog.timer
render_unit nemoclaw-slack-response-monitor.service.in nemoclaw-slack-response-monitor.service
render_unit nemoclaw-slack-response-monitor.timer.in nemoclaw-slack-response-monitor.timer

if proxy_is_configured; then
  render_unit nemoclaw-hermes-proxy.service.in nemoclaw-hermes-proxy.service
else
  systemctl --user disable --now nemoclaw-hermes-proxy.service >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/nemoclaw-hermes-proxy.service"
fi

systemctl --user daemon-reload
systemctl --user enable --now nemoclaw-hermes-gateway-forward.service
systemctl --user enable --now nemoclaw-hermes-watchdog.timer
systemctl --user enable --now nemoclaw-slack-response-monitor.timer
if proxy_is_configured; then
  systemctl --user enable --now nemoclaw-hermes-proxy.service
fi

printf '\nAuto-heal is enabled for sandbox %s.\n' "$AUTOHEAL_SANDBOX_NAME"
printf 'Run: bash scripts/autoheal/sanity-check.sh\n'
printf 'For a headless host: sudo loginctl enable-linger "$USER"\n'
