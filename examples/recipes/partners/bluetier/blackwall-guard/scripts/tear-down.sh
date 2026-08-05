#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
# SPDX-License-Identifier: Apache-2.0

# Tear down everything bring-up.sh created, in dependency order:
# sandbox -> per-sandbox provider -> (optionally) the provider profile.
#
#   scripts/tear-down.sh [--profile]
#
# Default scope removes the demo sandbox and its provider. --profile also
# deletes the imported nemoclaw-blackwall provider profile (leave it if other
# sandboxes use it). Mirrors the teardown conventions of
# recipes/nvidia/developer-community-chief-of-staff/scripts/tear-down.sh.
set -euo pipefail

SANDBOX_NAME="${SANDBOX_NAME:-blackwall-guard-demo}"
PROVIDER="$SANDBOX_NAME-blackwall"
PROFILE_ID="nemoclaw-blackwall"

echo "Deleting sandbox $SANDBOX_NAME (if present)"
openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true

echo "Deleting per-sandbox provider $PROVIDER"
openshell provider delete "$PROVIDER" 2>/dev/null || true

if [[ "${1:-}" == "--profile" ]]; then
  echo "Deleting provider profile $PROFILE_ID"
  openshell provider profile delete "$PROFILE_ID" 2>/dev/null || true
else
  echo "Provider profile $PROFILE_ID kept (pass --profile to remove it too)"
fi

echo "tear-down complete."
