#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Install the skill (with its synthetic data and tools) into an onboarded
# sandbox. When the sandbox uses the build.nvidia.com provider, also enable
# hosted policy retrieval (Nemotron embed and rerank):
#   1. import the provider profile that binds a credential to ai.api.nvidia.com,
#   2. create or update a provider from the key in .env and attach it, and
#   3. apply the egress policy in policies/, and
#   4. restart the sandbox when a provider was newly attached: the running agent only
#      sees a new credential after its container restarts (the workspace is kept), and
#   5. build the Kumo virtual environment (about 370 MB) from PyPI, using a temporary
#      pypi egress preset that is removed again unless it was already applied.
# When AUTO_ONTOLOGY_API_TOKEN is set, the same flow attaches a provider for a host-side
# Auto Ontology deployment (profile providers/auto-ontology.yaml, port AUTO_ONTOLOGY_PORT,
# default 4000) and tells the skill which URL to use.
# The raw key stays in the OpenShell gateway; the sandbox holds placeholders.
# Without that provider the skill still works and reports retrieval as blocked.
# Re-run after changing the skill, policies, or key.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || {
  echo "nemoclaw not in PATH — run scripts/onboard.sh first" >&2
  exit 1
}

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found — run scripts/onboard.sh first" >&2
  exit 1
fi

PROFILE_FILE="$EXAMPLE_DIR/providers/nvidia-ai-api.yaml"
PROFILE_ID="billing-integrity-nvidia-ai-api"
AI_PROVIDER="${NEMOCLAW_SANDBOX_NAME}-ai-api"
RESTART_NEEDED=0
HOSTED_ENABLED=0
ONTOLOGY_ENABLED=0
ONTOLOGY_PROFILE_FILE="$EXAMPLE_DIR/providers/auto-ontology.yaml"
ONTOLOGY_PROFILE_ID="billing-integrity-auto-ontology"
ONTOLOGY_PROVIDER="${NEMOCLAW_SANDBOX_NAME}-ontology"
ONTOLOGY_PORT="${AUTO_ONTOLOGY_PORT:-4000}"

enable_hosted_retrieval() {
  # Import the profile once. A profile cannot be edited in place, so an older one
  # without the Kumo route is replaced: detach and delete its provider, delete the
  # profile, and import the current file (the provider is created again below).
  if openshell provider profile export "$PROFILE_ID" >/dev/null 2>&1; then
    if openshell provider profile export "$PROFILE_ID" 2>/dev/null | grep -Fq 'kumo-relational/predictions'; then
      echo "Provider profile '$PROFILE_ID' already exists — keeping it."
    else
      echo "Provider profile '$PROFILE_ID' predates the Kumo route — recreating it."
      openshell sandbox provider detach "$NEMOCLAW_SANDBOX_NAME" "$AI_PROVIDER" >/dev/null 2>&1 || true
      openshell provider delete "$AI_PROVIDER" >/dev/null 2>&1 || true
      run openshell provider profile delete "$PROFILE_ID"
      run openshell provider profile import --file "$PROFILE_FILE"
    fi
  else
    run openshell provider profile import --file "$PROFILE_FILE"
  fi

  # The same build.nvidia.com key, under a second name, bound to ai.api.nvidia.com.
  export NVIDIA_AI_API_KEY="$NVIDIA_INFERENCE_API_KEY"
  if openshell provider get "$AI_PROVIDER" >/dev/null 2>&1; then
    run openshell provider update "$AI_PROVIDER" --credential NVIDIA_AI_API_KEY
  else
    run openshell provider create --name "$AI_PROVIDER" --type "$PROFILE_ID" \
      --credential NVIDIA_AI_API_KEY
  fi
  unset NVIDIA_AI_API_KEY

  if ! openshell sandbox provider list "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null | grep -Fq "$AI_PROVIDER"; then
    run openshell sandbox provider attach "$NEMOCLAW_SANDBOX_NAME" "$AI_PROVIDER"
    RESTART_NEEDED=1
  fi

  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy-add \
    --from-dir "$EXAMPLE_DIR/policies" \
    --yes
}

enable_auto_ontology() {
  # The profile pins one host port, so render it from AUTO_ONTOLOGY_PORT. A profile cannot be
  # edited in place: if the existing one has another port, replace it (and its provider).
  local rendered
  rendered="$(mktemp -d)/auto-ontology.yaml"
  sed "s/^  port: .*/  port: $ONTOLOGY_PORT/" "$ONTOLOGY_PROFILE_FILE" >"$rendered"
  if openshell provider profile export "$ONTOLOGY_PROFILE_ID" >/dev/null 2>&1; then
    if openshell provider profile export "$ONTOLOGY_PROFILE_ID" 2>/dev/null | grep -Eq "port: $ONTOLOGY_PORT\$"; then
      echo "Provider profile '$ONTOLOGY_PROFILE_ID' already exists for port $ONTOLOGY_PORT — keeping it."
    else
      echo "Provider profile '$ONTOLOGY_PROFILE_ID' is for another port — recreating it for $ONTOLOGY_PORT."
      openshell sandbox provider detach "$NEMOCLAW_SANDBOX_NAME" "$ONTOLOGY_PROVIDER" >/dev/null 2>&1 || true
      openshell provider delete "$ONTOLOGY_PROVIDER" >/dev/null 2>&1 || true
      run openshell provider profile delete "$ONTOLOGY_PROFILE_ID"
      run openshell provider profile import --file "$rendered"
    fi
  else
    run openshell provider profile import --file "$rendered"
  fi
  rm -rf "$(dirname "$rendered")"

  if openshell provider get "$ONTOLOGY_PROVIDER" >/dev/null 2>&1; then
    run openshell provider update "$ONTOLOGY_PROVIDER" --credential AUTO_ONTOLOGY_API_TOKEN
  else
    run openshell provider create --name "$ONTOLOGY_PROVIDER" --type "$ONTOLOGY_PROFILE_ID" \
      --credential AUTO_ONTOLOGY_API_TOKEN
  fi
  if ! openshell sandbox provider list "$NEMOCLAW_SANDBOX_NAME" 2>/dev/null | grep -Fq "$ONTOLOGY_PROVIDER"; then
    run openshell sandbox provider attach "$NEMOCLAW_SANDBOX_NAME" "$ONTOLOGY_PROVIDER"
    RESTART_NEEDED=1
  fi
}

SKILL_DIR_IN_SANDBOX="/sandbox/.openclaw/workspace/skills/provider-billing-integrity"

setup_kumo_environment() {
  local added_pypi=0
  if nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy list 2>/dev/null | grep -Eq '● +pypi'; then
    echo "pypi egress preset already applied — leaving it in place."
  else
    run nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy-add pypi --yes
    added_pypi=1
  fi
  local status=0
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" exec --timeout 900 -- bash -c '
    set -e
    V=/sandbox/kumo-venv
    if "$V/bin/python" -c "import kumo_relational_client, pandas" 2>/dev/null; then
      echo "Kumo environment already present"; exit 0
    fi
    python3 -m venv "$V"
    "$V/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: -r "'"$SKILL_DIR_IN_SANDBOX"'/utilities/requirements-kumo.txt"
  ' || status=$?
  if [[ "$added_pypi" == "1" ]]; then
    run nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy-remove pypi --yes
  fi
  if [[ "$status" != "0" ]]; then
    echo "warning: the Kumo environment could not be built; kumo_predict.py will report blocked." >&2
  fi
}

echo "Installing provider-billing-integrity into sandbox '$NEMOCLAW_SANDBOX_NAME'"
if [[ "${NEMOCLAW_PROVIDER:-build}" == "build" && -n "${NVIDIA_INFERENCE_API_KEY:-}" ]]; then
  command -v openshell >/dev/null || {
    echo "openshell not in PATH" >&2
    exit 1
  }
  echo "Enabling hosted models (Nemotron embed and rerank, Kumo)"
  enable_hosted_retrieval
  HOSTED_ENABLED=1
else
  echo "note: hosted models not enabled (needs NEMOCLAW_PROVIDER=build and" >&2
  echo "      NVIDIA_INFERENCE_API_KEY in .env). The skill will report retrieval and Kumo as blocked." >&2
fi

if [[ -n "${AUTO_ONTOLOGY_API_TOKEN:-}" ]]; then
  command -v openshell >/dev/null || {
    echo "openshell not in PATH" >&2
    exit 1
  }
  echo "Enabling Auto Ontology (host.openshell.internal:$ONTOLOGY_PORT)"
  enable_auto_ontology
  ONTOLOGY_ENABLED=1
fi

run nemoclaw "$NEMOCLAW_SANDBOX_NAME" skill install \
  "$EXAMPLE_DIR/skills/provider-billing-integrity"

if [[ "$ONTOLOGY_ENABLED" == "1" ]]; then
  # The skill reads its Auto Ontology URL from this file (the sandbox has no other config channel).
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" exec -- bash -c \
    "printf '%s\n' http://host.openshell.internal:$ONTOLOGY_PORT > $SKILL_DIR_IN_SANDBOX/utilities/ontology.url"
fi

if [[ "$HOSTED_ENABLED" == "1" ]]; then
  setup_kumo_environment
fi

if [[ "$RESTART_NEEDED" == "1" ]]; then
  echo "Restarting the sandbox so the agent picks up the new credential (workspace is kept)"
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" stop
  run nemoclaw "$NEMOCLAW_SANDBOX_NAME" start
fi

echo
echo "Installed. Ensure the sandbox is running with: bash scripts/start.sh"
