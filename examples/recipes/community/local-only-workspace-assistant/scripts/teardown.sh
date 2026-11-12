#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove the resources that scripts/bring-up.sh recorded. This script does not
# remove a sandbox, a provider, a provider profile, an image, or a model that
# existed before setup.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${DIR}/_lib.sh"

purge_models=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-models) purge_models=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--purge-models]"
      echo "  --purge-models  also delete the recipe volume that holds the downloaded model"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

load_env

echo "== 1/4 delete the recipe sandbox =="
if ! state_has sandbox "${SANDBOX_NAME}"; then
  echo "Setup did not create sandbox ${SANDBOX_NAME}; leaving it unchanged."
elif ! command -v openshell >/dev/null 2>&1; then
  echo "openshell not found; sandbox ${SANDBOX_NAME} was not deleted." >&2
else
  if [[ "$(sandbox_phase)" != "Missing" ]]; then
    openshell sandbox delete "${SANDBOX_NAME}"
    # Deletion finishes in the background. The provider cannot be deleted
    # while the sandbox still holds it.
    for _ in $(seq 1 60); do
      [[ "$(sandbox_phase)" == "Missing" ]] && break
      sleep 2
    done
  fi
  if [[ "$(sandbox_phase)" != "Missing" ]]; then
    echo "Sandbox ${SANDBOX_NAME} is still listed. Run this script again later." >&2
    exit 1
  fi
  state_remove sandbox "${SANDBOX_NAME}"
fi

echo "== 2/4 delete the recipe provider and its profile =="
if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell not found; the provider and its profile were not deleted." >&2
else
  if ! state_has provider "${INFERENCE_PROVIDER_NAME}"; then
    echo "Setup did not create provider ${INFERENCE_PROVIDER_NAME}; leaving it unchanged."
  else
    if openshell provider get "${INFERENCE_PROVIDER_NAME}" >/dev/null 2>&1; then
      openshell provider delete "${INFERENCE_PROVIDER_NAME}"
    fi
    state_remove provider "${INFERENCE_PROVIDER_NAME}"
  fi
  if ! state_has profile "${PROFILE_ID}"; then
    echo "Setup did not import provider profile ${PROFILE_ID}; leaving it unchanged."
  else
    if openshell profile describe "${PROFILE_ID}" >/dev/null 2>&1; then
      openshell profile delete "${PROFILE_ID}"
    fi
    state_remove profile "${PROFILE_ID}"
  fi
fi

echo "== 3/4 delete the recipe sandbox image =="
if ! state_has image "${SANDBOX_IMAGE}"; then
  echo "Setup did not build image ${SANDBOX_IMAGE}; leaving it unchanged."
elif ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; image ${SANDBOX_IMAGE} was not deleted." >&2
else
  if docker image inspect "${SANDBOX_IMAGE}" >/dev/null 2>&1; then
    docker image rm "${SANDBOX_IMAGE}" >/dev/null
  fi
  state_remove image "${SANDBOX_IMAGE}"
fi

echo "== 4/4 stop the recipe-owned inference server =="
if ! state_has compose ollama; then
  echo "Setup did not start the inference server; leaving Docker unchanged."
elif ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; the inference server was not stopped." >&2
else
  if [[ "${purge_models}" == 1 ]]; then
    compose down --volumes
  else
    compose down
    echo "The model volume is kept. Run with --purge-models to delete it."
  fi
  state_remove compose ollama
  state_remove device gpu
  state_remove device cpu
fi

echo "Teardown complete."
