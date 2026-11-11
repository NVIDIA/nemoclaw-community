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
SANDBOX_WORKSPACE="/sandbox/workspace"
SANDBOX_SKILL_DIR="/sandbox/.openclaw/skills/workspace-assistant"

load_env() {
  if [[ -f "${EXAMPLE_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${EXAMPLE_DIR}/.env"
    set +a
  fi
  export SANDBOX_NAME="${SANDBOX_NAME:-local-only-workspace-assistant}"
  export WORKSPACE_DIR="${WORKSPACE_DIR:-./fixtures/workspace}"
  export WORKSPACE_MAX_FILE_BYTES="${WORKSPACE_MAX_FILE_BYTES:-1048576}"
  export INFERENCE_MODEL="${INFERENCE_MODEL:-nemotron-3-nano:4b-q4_K_M}"
  export INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-local-only-ollama}"
  export OLLAMA_PUBLISH_HOST="${OLLAMA_PUBLISH_HOST:-127.0.0.1}"
  export OLLAMA_PORT="${OLLAMA_PORT:-11434}"
  export INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-http://127.0.0.1:${OLLAMA_PORT}/v1}"
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

# Standard input is closed so a call inside a `while read` loop cannot consume
# the lines that the loop still has to read.
sandbox_exec() {
  openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- "$@" </dev/null
}

sandbox_copy() {
  openshell sandbox cp "$1" "${SANDBOX_NAME}:$2" </dev/null
}

# Setup records each resource that it creates. Teardown removes only those.
state_add() {
  mkdir -p "${RUN_DIR}"
  state_has "$1" "$2" || printf '%s=%s\n' "$1" "$2" >>"${STATE_FILE}"
}

state_has() {
  [[ -f "${STATE_FILE}" ]] && grep -Fxq "$1=$2" "${STATE_FILE}"
}

state_remove() {
  [[ -f "${STATE_FILE}" ]] || return 0
  grep -Fxv "$1=$2" "${STATE_FILE}" >"${STATE_FILE}.tmp" || true
  mv "${STATE_FILE}.tmp" "${STATE_FILE}"
}
