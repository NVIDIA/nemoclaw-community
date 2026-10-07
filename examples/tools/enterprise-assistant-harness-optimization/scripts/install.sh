#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Install host tools, Harbor, OpenShell, the Hermes image, and the fictional MCP service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CURRENT_STEP="startup"
HARBOR_PYTHON="$ROOT/.harbor-venv/bin/python"
MCP_PYTHON="$ROOT/.mcp-venv/bin/python"
SUPERVISOR_IMAGE="ghcr.io/nvidia/openshell/supervisor@sha256:d7b5264bb6bc56f4796e6fa3617b8e4a8d785be0b7293542efd8cc250b0fb67a"

trap 'status=$?; echo ""; echo "ERROR: ${CURRENT_STEP} failed (exit ${status})."; echo "Fix the problem above, then re-run ./scripts/install.sh"; exit "$status"' ERR

step() {
  CURRENT_STEP="$1"
  echo ""
  echo "==> ${CURRENT_STEP}"
}

step "Install host packages"
sudo apt-get update
sudo apt-get install -y ca-certificates curl git gh jq make python3

if ! command -v docker >/dev/null 2>&1; then
  step "Install Docker"
  curl -fsSL https://get.docker.com | sudo sh
fi

step "Allow this user to run Docker"
sudo usermod -aG docker "$USER"

step "Install uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="${HOME}/.local/bin:${PATH}"
hash -r
command -v uv >/dev/null

step "Check Docker access"
if ! docker info >/dev/null 2>&1; then
  trap - ERR
  echo ""
  echo "ERROR: Check Docker access failed."
  echo "Docker is installed, but this session cannot use the Docker daemon."
  echo "Disconnect and reconnect to the host (or run 'newgrp docker'), then re-run:"
  echo "  ./scripts/install.sh"
  exit 1
fi

step "Prepare Harbor"
mkdir -p .runs
if [[ ! -x "$HARBOR_PYTHON" ]]; then
  uv venv .harbor-venv --python 3.12
fi
uv pip install --python "$HARBOR_PYTHON" 'harbor==0.22.0'
"$ROOT/.harbor-venv/bin/harbor" --version
make test PYTHON="$HARBOR_PYTHON"
make validate-fixture PYTHON="$HARBOR_PYTHON" FIXTURE=fixtures/world-v2.json

step "Install OpenShell"
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | \
  OPENSHELL_VERSION=v0.1.2 sh
export PATH="${HOME}/.local/bin:${PATH}"
hash -r
command -v openshell >/dev/null
openshell --version

step "Start the OpenShell gateway"
if ! systemctl --user enable --now openshell-gateway.service; then
  trap - ERR
  echo ""
  echo "ERROR: Start the OpenShell gateway failed."
  echo "systemctl --user could not start openshell-gateway.service."
  echo "On an SSH session, enable a user systemd instance and re-run ./scripts/install.sh:"
  echo "  sudo loginctl enable-linger \"${USER}\""
  echo "  export XDG_RUNTIME_DIR=\"/run/user/$(id -u)\""
  exit 1
fi
openshell status
openshell doctor check
openshell gateway info

step "Pull the OpenShell supervisor image"
docker pull "$SUPERVISOR_IMAGE"

step "Build the Hermes image"
docker build -f openshell/Dockerfile -t hermes-flywheel-openshell:0.3 .

step "Install the fictional MCP service"
if [[ ! -x "$MCP_PYTHON" ]]; then
  uv venv .mcp-venv --python 3.12
fi
uv pip install --python "$MCP_PYTHON" -e '.[remote-mcp]'

step "Configure the NVIDIA Build provider"
if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  if [[ ! -t 0 ]]; then
    trap - ERR
    echo ""
    echo "ERROR: Configure the NVIDIA Build provider failed."
    echo "NVIDIA_API_KEY is not set, and this is not an interactive terminal."
    echo "Export NVIDIA_API_KEY and re-run ./scripts/install.sh"
    exit 1
  fi
  printf 'NVIDIA Build API key: '
  read -rs NVIDIA_API_KEY
  printf '\n'
  export NVIDIA_API_KEY
fi
if [[ -z "${NVIDIA_API_KEY}" ]]; then
  trap - ERR
  echo ""
  echo "ERROR: Configure the NVIDIA Build provider failed."
  echo "No NVIDIA Build API key was provided."
  exit 1
fi

if ! curl --fail-with-body -sS https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer ${NVIDIA_API_KEY}" -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/nemotron-3-ultra-550b-a55b","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":256,"reasoning_effort":"none","stream":false}' \
  -o .runs/provider-smoke.json; then
  trap - ERR
  echo ""
  echo "ERROR: Configure the NVIDIA Build provider failed."
  echo "NVIDIA Build rejected the API key. Response:"
  cat .runs/provider-smoke.json >&2 || true
  echo ""
  echo "Confirm the key from https://build.nvidia.com/ and re-run ./scripts/install.sh"
  exit 1
fi
jq '{model,choices}' .runs/provider-smoke.json
openshell profile lint -f openshell/provider-nvidia.yaml
openshell profile import -f openshell/provider-nvidia.yaml

set +e
provider_output="$(openshell provider create --name hermes-nvidia --type hermes-nvidia-build --credential NVIDIA_API_KEY 2>&1)"
provider_status=$?
set -e
printf '%s\n' "$provider_output"
if [[ "$provider_status" -ne 0 ]]; then
  if grep -Eqi 'already exists|already configured|duplicate' <<<"$provider_output"; then
    echo "OpenShell provider hermes-nvidia is already configured; continuing."
  else
    trap - ERR
    echo ""
    echo "ERROR: Configure the NVIDIA Build provider failed."
    echo "Could not create the OpenShell provider hermes-nvidia."
    exit 1
  fi
fi
unset NVIDIA_API_KEY

trap - ERR
echo ""
echo "Install finished."
echo "Start the host MCP service and a sandbox with:"
echo "  .harbor-venv/bin/python scripts/try_agent.py --arm baseline --name hermes-try"
