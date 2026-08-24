#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Add the OpenShell policy and install the remote-operator skill into an
# existing NemoClaw sandbox. Does not create a sandbox and does not start
# gbr-agent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"
SANDBOX_NAME="${SANDBOX_NAME:-gbr-pair}"
POLICY_PATH="$EXAMPLE_DIR/policy.yaml"
ALLOW_POLICY_REPLACE="${GBR_PAIR_ALLOW_POLICY_REPLACE:-0}"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$EXAMPLE_DIR/.env"
  set +a
fi

if ! command -v nemoclaw >/dev/null 2>&1; then
  echo "nemoclaw not in PATH. Install NemoClaw, then re-run this script:" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash" >&2
  echo "Host-side gbr-agent can still be installed with scripts/install-gbr-agent.sh or scripts/install-gbr-agent.ps1." >&2
  exit 1
fi

command -v openshell >/dev/null 2>&1 || {
  echo "openshell not in PATH — is the gateway installed?" >&2
  exit 1
}

if ! openshell sandbox list 2>/dev/null | grep -qE "^[[:space:]]*${SANDBOX_NAME}[[:space:]]"; then
  echo "Sandbox '${SANDBOX_NAME}' was not found." >&2
  echo "Create a dedicated sandbox first, for example:" >&2
  echo "  export NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_SANDBOX_NAME=${SANDBOX_NAME}" >&2
  echo "  nemoclaw onboard --non-interactive --agents \"$EXAMPLE_DIR/agents.yaml\"" >&2
  echo "Then re-run this script." >&2
  exit 1
fi

echo "== apply OpenShell policy =="
if command -v nemoclaw >/dev/null 2>&1; then
  nemoclaw "$SANDBOX_NAME" policy-add --from-file "$POLICY_PATH" --yes
elif [[ "$ALLOW_POLICY_REPLACE" == "1" ]]; then
  echo "nemoclaw not found; replacing the full sandbox policy with openshell."
  echo "Only do this for a dedicated sandbox created for this recipe."
  openshell policy set --policy "$POLICY_PATH" --wait "$SANDBOX_NAME"
else
  echo "nemoclaw not found, so this script will not replace the full sandbox policy." >&2
  exit 1
fi

echo "== install skill =="
bash "$SCRIPT_DIR/install.sh"

echo "Onboard complete. Host: keep gbr-agent on the host, not in the sandbox."
echo "Verify with: bash scripts/verify.sh"
