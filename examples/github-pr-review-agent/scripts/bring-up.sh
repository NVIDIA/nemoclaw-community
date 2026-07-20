#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir
# SPDX-License-Identifier: Apache-2.0
#
# Bring up the github-pr-review-agent NemoClaw sandbox.
# Usage: bash scripts/bring-up.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"

# load env
if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a; source "$EXAMPLE_DIR/.env"; set +a
fi

: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set in .env}"
: "${GITHUB_REPO:?GITHUB_REPO must be set in .env (owner/repo format)}"

echo "==> substituting policy placeholders..."
sed "s|__GITHUB_REPO__|${GITHUB_REPO}|g" \
  "$EXAMPLE_DIR/policy.yaml" > /tmp/pr-review-policy.yaml

echo "==> starting NemoClaw sandbox..."
openshell sandbox create --from nemoclaw
openshell sandbox run \
  --policy /tmp/pr-review-policy.yaml \
  --env GITHUB_TOKEN="$GITHUB_TOKEN" \
  --env GITHUB_REPO="$GITHUB_REPO" \
  --env NVIDIA_API_KEY="${NVIDIA_API_KEY:-}" \
  --env POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-900}" \
  -- hermes start

echo "==> sandbox running. Hermes is watching $GITHUB_REPO for new PRs."
