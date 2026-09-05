#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
# SPDX-License-Identifier: Apache-2.0

# Bring up the blackwall-guard integration end to end:
#
#   1. preflight        — openshell CLI present, gateway reachable, env set
#   2. provider profile — import providers/blackwall.yaml (id: nemoclaw-blackwall)
#   3. provider         — create/update $SANDBOX_NAME-blackwall with the real
#                         API key held GATEWAY-side (never enters the sandbox)
#   4. sandbox          — create $SANDBOX_NAME with policy.yaml and the
#                         provider attached, from an OpenClaw-capable image
#   5. plugin           — the sandbox image bakes the plugin in (see
#                         "Install & enable" in ../README.md); this phase
#                         verifies it is present and enabled
#
# Environment (required):
#   BLACKWALL_API_KEY   real BLACK_WALL key — consumed HOST-side by phase 3
#                       and handed to the gateway; the sandbox only ever sees
#                       the OpenShell placeholder.
#   SANDBOX_IMAGE       an OpenClaw-capable sandbox image with the plugin
#                       directory baked in (README, "Install & enable").
# Environment (optional):
#   SANDBOX_NAME        default: blackwall-guard-demo
#
# Provider/policy/sandbox commands follow the conventions of
# recipes/nvidia/developer-community-chief-of-staff/scripts/{02-providers,03-sandbox}.sh.
# Validate against your OpenShell version; `openshell ... --help` is
# authoritative if flags have moved.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$DIR")"
SANDBOX_NAME="${SANDBOX_NAME:-blackwall-guard-demo}"
PROFILE_ID="nemoclaw-blackwall"
PROVIDER="$SANDBOX_NAME-blackwall"

echo "== 1/5 preflight =="
command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }
[[ -n "${BLACKWALL_API_KEY:-}" ]] || { echo "BLACKWALL_API_KEY is required (host-side only)" >&2; exit 1; }
[[ -n "${SANDBOX_IMAGE:-}" ]] || { echo "SANDBOX_IMAGE is required (OpenClaw-capable image with the plugin baked in — see README 'Install & enable')" >&2; exit 1; }
if ! openshell settings get --global 2>/dev/null | grep -qE "providers_v2_enabled\s*=\s*true"; then
  echo "providers_v2_enabled is not set at gateway-global scope." >&2
  echo "Run: openshell settings set --global --key providers_v2_enabled --value true --yes" >&2
  exit 1
fi

echo "== 2/5 provider profile ($PROFILE_ID) =="
# Delete-then-import so YAML edits land on re-run; tolerate the in-use case
# (profile attached to a live sandbox cannot be deleted or re-imported).
openshell provider profile delete "$PROFILE_ID" >/dev/null 2>&1 || true
if ! import_out="$(openshell provider profile import --file "$EXAMPLE_DIR/providers/blackwall.yaml" 2>&1)"; then
  if grep -qi "already exists" <<<"$import_out"; then
    echo "  profile already registered (attached to a live sandbox; not re-imported)"
  else
    printf '%s\n' "$import_out" >&2
    exit 1
  fi
fi

echo "== 3/5 provider ($PROVIDER) =="
# The real key lives gateway-side from here on. Update-or-create for re-runs.
if openshell provider get "$PROVIDER" >/dev/null 2>&1; then
  openshell provider update "$PROVIDER" --credential "BLACKWALL_API_KEY=$BLACKWALL_API_KEY"
else
  openshell provider create --name "$PROVIDER" --type "$PROFILE_ID" \
    --credential "BLACKWALL_API_KEY=$BLACKWALL_API_KEY"
fi

echo "== 4/5 sandbox ($SANDBOX_NAME) =="
if openshell sandbox list 2>/dev/null | grep -qE "^\s*$SANDBOX_NAME\s"; then
  echo "  sandbox exists; re-applying policy"
else
  openshell sandbox create \
    --name "$SANDBOX_NAME" \
    --image "$SANDBOX_IMAGE" \
    --policy "$EXAMPLE_DIR/policy.yaml" \
    --provider "$PROVIDER"
fi
openshell policy set --policy "$EXAMPLE_DIR/policy.yaml" --wait "$SANDBOX_NAME"

echo "== 5/5 plugin enablement check =="
# The plugin ships in the image (README, "Install & enable"). Its registration
# line is deterministic — the plugin logs it on load.
if openshell sandbox logs "$SANDBOX_NAME" 2>/dev/null | grep -q "\[blackwall\]"; then
  echo "  plugin registered (found [blackwall] in sandbox logs)"
else
  echo "  NOTE: no [blackwall] log line yet — the agent may not have started."
  echo "  After the agent starts, run scripts/verify.sh to prove interception."
fi

echo
echo "bring-up complete. Next: scripts/verify.sh (inside-sandbox stages prove"
echo "credential injection and that a real tool call is intercepted)."
