#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Remove only the optional user-level auto-heal services.

set -euo pipefail
case "${1:-}" in
  "") ;;
  -h|--help)
    printf 'Usage: bash scripts/autoheal/uninstall.sh\n\nRemoves only the optional NemoClaw auto-heal user services.\n'
    exit 0
    ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/nemoclaw-autoheal"
units=(
  nemoclaw-hermes-proxy.service
  nemoclaw-hermes-gateway-forward.service
  nemoclaw-hermes-watchdog.service
  nemoclaw-hermes-watchdog.timer
  nemoclaw-slack-response-monitor.service
  nemoclaw-slack-response-monitor.timer
)

for unit in "${units[@]}"; do
  systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload
rm -rf "$CONFIG_DIR"
printf 'NemoClaw auto-heal user services were removed.\n'
