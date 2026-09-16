#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

GATEWAY_NAME="${NEMOCLAW_GATEWAY_NAME:-nemoclaw}"
GATEWAY_ENDPOINT="${NEMOCLAW_GATEWAY_ENDPOINT:-https://127.0.0.1:8080}"
MANAGEMENT_ENV="/etc/nemoclaw/gateway-management.env"
OPENSHELL_BIN="${OPENSHELL_BIN:-$HOME/.local/bin/openshell}"
[[ -x "$OPENSHELL_BIN" ]] || OPENSHELL_BIN="$(command -v openshell || true)"

if [[ -z "$OPENSHELL_BIN" || ! -x "$OPENSHELL_BIN" ]]; then
  printf 'The updated OpenShell client is unavailable. Run the maintained NemoClaw installer first.\n' >&2
  exit 1
fi

if [[ ! -r "$MANAGEMENT_ENV" ]]; then
  printf 'This does not appear to be a supported NemoClaw Brev launchable host: %s is unavailable.\n' "$MANAGEMENT_ENV" >&2
  exit 1
fi

if [[ "$(systemctl is-active openshell-gateway.service 2>/dev/null || true)" == active ]]; then
  # The launchable owns this file. It contains local gateway paths, not
  # inference credentials. Use it only to prove the legacy gateway is empty.
  set -a
  # shellcheck disable=SC1091
  . "$MANAGEMENT_ENV"
  set +a

  if [[ -z "${OPENSHELL_LOCAL_TLS_DIR:-}" || ! -r "$OPENSHELL_LOCAL_TLS_DIR/ca.crt" ]]; then
    printf 'The Brev gateway TLS directory is incomplete. No service was changed.\n' >&2
    exit 1
  fi

  if ! "$OPENSHELL_BIN" gateway select "$GATEWAY_NAME" >/dev/null 2>&1; then
    "$OPENSHELL_BIN" gateway add --name "$GATEWAY_NAME" --local "$GATEWAY_ENDPOINT" >/dev/null
  fi

  sandbox_output="$($OPENSHELL_BIN sandbox list 2>&1)" || {
    printf 'The Brev gateway could not be inspected. No service was changed.\n%s\n' "$sandbox_output" >&2
    exit 1
  }
  if ! grep -Fq 'No sandboxes found.' <<<"$sandbox_output"; then
    printf 'The Brev gateway is not empty. No service was changed.\n%s\n' "$sandbox_output" >&2
    exit 1
  fi

  printf 'The legacy Brev gateway is empty. Handing lifecycle control to the updated NemoClaw installation.\n'
  sudo -n systemctl disable --now openshell-gateway.service
fi

if [[ "$(systemctl is-active openshell-gateway.service 2>/dev/null || true)" == active ]]; then
  printf 'The legacy Brev gateway service is still active.\n' >&2
  exit 1
fi

"$OPENSHELL_BIN" gateway remove "$GATEWAY_NAME" >/dev/null 2>&1 || true

printf 'Brev gateway handoff is ready. scripts/onboard.sh will start the current gateway in compatibility-container mode.\n'
