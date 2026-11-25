#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers. Source this file from the other scripts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${EXAMPLE_DIR}/.run"
STATE_FILE="${RUN_DIR}/created"
COMPOSE_FILE="${EXAMPLE_DIR}/docker-compose.yml"
COMPOSE_GPU_FILE="${EXAMPLE_DIR}/docker-compose.gpu.yml"
POLICY_FILE="${EXAMPLE_DIR}/policies/local-only.yaml"
PROFILE_FILE="${EXAMPLE_DIR}/policies/ollama-provider-profile.yaml"
# The `id` in PROFILE_FILE. Setup imports the profile under this ID.
PROFILE_ID="local-only-ollama"
SANDBOX_WORKSPACE="/sandbox/workspace"
SANDBOX_SKILL_DIR="/sandbox/.openclaw/skills/workspace-assistant"
SANDBOX_OPENCLAW_CONFIG="/sandbox/.openclaw/openclaw.json"
# The `container_name` and volume `name` in COMPOSE_FILE.
OLLAMA_CONTAINER="local-only-workspace-assistant-ollama"
MODEL_VOLUME="local-only-workspace-assistant-ollama-models"

load_env() {
  if [[ -f "${EXAMPLE_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${EXAMPLE_DIR}/.env"
    set +a
  fi
  # OpenShell 0.1 limits sandbox names to 19 characters.
  export SANDBOX_NAME="${SANDBOX_NAME:-local-only-assist}"
  export WORKSPACE_DIR="${WORKSPACE_DIR:-./fixtures/workspace}"
  export WORKSPACE_MAX_FILE_BYTES="${WORKSPACE_MAX_FILE_BYTES:-1048576}"
  export INFERENCE_MODEL="${INFERENCE_MODEL:-nemotron-3-nano:4b-q4_K_M}"
  export INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-local-only-ollama}"
  export OLLAMA_PUBLISH_HOST="${OLLAMA_PUBLISH_HOST:-127.0.0.1}"
  export OLLAMA_PORT="${OLLAMA_PORT:-11434}"
  # URL that processes inside the sandbox call. host.openshell.internal is the
  # OpenShell name for the gateway host.
  export INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-http://host.openshell.internal:${OLLAMA_PORT}/v1}"
  export SANDBOX_IMAGE="${SANDBOX_IMAGE:-local-only-workspace-assistant:local}"
  export LOCAL_ENDPOINT_EXTRA_HOSTS="${LOCAL_ENDPOINT_EXTRA_HOSTS:-}"
  export INFERENCE_DEVICE="${INFERENCE_DEVICE:-auto}"
  export ALLOW_MISSING_LANDLOCK="${ALLOW_MISSING_LANDLOCK:-0}"
  # A relative workspace path is relative to the recipe directory.
  case "${WORKSPACE_DIR}" in
    /*) ;;
    *) WORKSPACE_DIR="${EXAMPLE_DIR}/${WORKSPACE_DIR}" ;;
  esac
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    return 1
  }
}

# Run the recipe's Python checks. They use only the standard library.
localonly() {
  PYTHONPATH="${EXAMPLE_DIR}/src" python3 -m localonly "$@"
}

host_has_nvidia_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1
}

# Print "gpu" or "cpu" for the INFERENCE_DEVICE setting. Fail when the setting
# asks for a GPU that the host does not have.
resolve_inference_device() {
  case "${INFERENCE_DEVICE}" in
    cpu) echo cpu ;;
    gpu)
      host_has_nvidia_gpu || {
        echo "INFERENCE_DEVICE=gpu, but 'nvidia-smi -L' found no NVIDIA GPU." >&2
        return 1
      }
      echo gpu
      ;;
    auto) if host_has_nvidia_gpu; then echo gpu; else echo cpu; fi ;;
    *)
      echo "INFERENCE_DEVICE must be auto, gpu, or cpu (got '${INFERENCE_DEVICE}')." >&2
      return 1
      ;;
  esac
}

# WSL2 kernels report "microsoft" in the kernel version string.
host_is_wsl2() {
  grep -qi microsoft /proc/version 2>/dev/null
}

# Setup records the device that it selected. Every later compose call uses
# the same files, so teardown matches what setup started.
compose_file_args() {
  printf '%s\n' "${COMPOSE_FILE}"
  if state_has device gpu; then
    printf '%s\n' "${COMPOSE_GPU_FILE}"
  fi
}

compose() {
  if state_has device gpu; then
    docker compose -f "${COMPOSE_FILE}" -f "${COMPOSE_GPU_FILE}" "$@"
  else
    docker compose -f "${COMPOSE_FILE}" "$@"
  fi
}

# Print the phase of the named sandbox, or "Missing".
sandbox_phase() {
  local name="${1:-$SANDBOX_NAME}"
  openshell sandbox list 2>/dev/null | awk -v wanted="$name" '
    { gsub(/\033\[[0-9;]*m/, "") }
    NR > 1 && $1 == wanted { print $NF; found = 1; exit }
    END { if (!found) print "Missing" }
  '
}

sandbox_is_ready() {
  [[ "$(sandbox_phase "$@" | tr '[:upper:]' '[:lower:]')" == "ready" ]]
}

# Delete the recipe sandbox and wait until OpenShell no longer lists it.
# Deletion finishes in the background, and the provider cannot be deleted
# while the sandbox still holds it.
sandbox_delete_and_wait() {
  if [[ "$(sandbox_phase)" != "Missing" ]]; then
    openshell sandbox delete "${SANDBOX_NAME}"
    for _ in $(seq 1 60); do
      [[ "$(sandbox_phase)" == "Missing" ]] && break
      sleep 2
    done
  fi
  [[ "$(sandbox_phase)" == "Missing" ]]
}

# Print the model reference and the inference URL in the OpenClaw
# configuration of the running sandbox, as "<model reference> <URL>". The
# image build writes both, so they show which settings the sandbox was
# created with.
sandbox_inference_settings() {
  sandbox_exec python3 -c '
import json, sys
config = json.load(open(sys.argv[1]))
print(
    config["agents"]["defaults"]["model"]["primary"],
    config["models"]["providers"]["inference"]["baseUrl"],
)
' "${SANDBOX_OPENCLAW_CONFIG}" | tr -d '\r' | tail -n 1
}

# Standard input is closed so a call inside a `while read` loop cannot consume
# the lines that the loop still has to read.
sandbox_exec() {
  openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- "$@" </dev/null
}

# Copy one host file to an exact path in the sandbox. Setup has already
# selected each file, so Git ignore rules must not drop one silently.
sandbox_copy() {
  openshell sandbox upload --no-git-ignore "${SANDBOX_NAME}" "$1" "$2" </dev/null
}

# Print an identifier for the current model volume, or return 1 when the
# volume does not exist. Including CreatedAt distinguishes a volume that
# setup created from another volume created outside setup under the same
# name.
model_volume_id() {
  local raw created_at
  raw="$(docker volume inspect "${MODEL_VOLUME}" 2>/dev/null)" || return 1
  created_at="$(printf '%s' "${raw}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    item = data[0] if isinstance(data, list) and data else data
    value = item.get("CreatedAt", "") if isinstance(item, dict) else ""
    print(str(value).strip())
except Exception:
    print("")
' | tr -d '\r\n')"
  if [[ -n "${created_at}" ]]; then
    printf '%s@%s\n' "${MODEL_VOLUME}" "${created_at}"
  else
    printf '%s\n' "${MODEL_VOLUME}"
  fi
}

# Setup records each resource that it creates. Teardown removes only those.
state_add() {
  mkdir -p "${RUN_DIR}"
  state_has "$1" "$2" || printf '%s=%s\n' "$1" "$2" >>"${STATE_FILE}"
}

state_has() {
  [[ -f "${STATE_FILE}" ]] && grep -Fxq "$1=$2" "${STATE_FILE}"
}

state_has_key() {
  [[ -f "${STATE_FILE}" ]] && grep -Eq "^$1=" "${STATE_FILE}"
}

state_remove() {
  [[ -f "${STATE_FILE}" ]] || return 0
  grep -Fxv "$1=$2" "${STATE_FILE}" >"${STATE_FILE}.tmp" || true
  mv "${STATE_FILE}.tmp" "${STATE_FILE}"
}

state_remove_key() {
  [[ -f "${STATE_FILE}" ]] || return 0
  grep -Ev "^$1=" "${STATE_FILE}" >"${STATE_FILE}.tmp" || true
  mv "${STATE_FILE}.tmp" "${STATE_FILE}"
}
