#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Start the recipe-owned inference server, register it with OpenShell as a
# provider, create a dedicated sandbox with the local-only policy and that
# provider attached, and copy the approved folder into the sandbox.
#
# This script downloads two container images and a model, builds a local
# image, and adds a provider profile and a provider to the selected OpenShell
# gateway. Read the README section "What Setup Changes" before you run it.
# It requires OpenShell 0.1 or later.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${DIR}/_lib.sh"

load_env
mkdir -p "${RUN_DIR}"

echo "== 1/7 check inputs =="
require_command python3
require_command docker
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose is required: 'docker compose version' failed." >&2
  exit 1
}
require_command openshell
openshell status >/dev/null 2>&1 || {
  echo "The OpenShell gateway is not reachable: 'openshell status' failed." >&2
  exit 1
}
localonly check-policy "${POLICY_FILE}"
localonly check-profile "${PROFILE_FILE}" --base-url "${INFERENCE_BASE_URL}"
localonly check-publish-host "${OLLAMA_PUBLISH_HOST}"
localonly check-endpoint "${INFERENCE_BASE_URL}" --extra-hosts "${LOCAL_ENDPOINT_EXTRA_HOSTS}"
localonly list-workspace "${WORKSPACE_DIR}" \
  --max-file-bytes "${WORKSPACE_MAX_FILE_BYTES}" >"${RUN_DIR}/workspace-files.tsv"
echo "Approved files to copy: $(wc -l <"${RUN_DIR}/workspace-files.tsv" | tr -d ' ')"

echo "== 2/7 select the inference device and check the kernel =="
device="$(resolve_inference_device)"
state_remove device gpu
state_remove device cpu
state_add device "${device}"
if [[ "${device}" == "gpu" ]]; then
  nvidia-smi -L
else
  echo "Inference device: CPU. The sandbox boundary tests do not need a GPU."
  echo "This run gives no evidence about GPU serving."
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  # The sandbox runs on the kernel of the Docker virtual machine, which this
  # script cannot inspect from the host.
  echo "Host is not Linux; the Landlock check is skipped."
  echo "Cases S02 and S03 of the test suite measure filesystem enforcement."
elif grep -qw landlock /sys/kernel/security/lsm 2>/dev/null; then
  echo "Kernel lists the Landlock security module."
elif [[ "${ALLOW_MISSING_LANDLOCK}" == "1" ]]; then
  echo "Kernel does not list Landlock. Continuing because ALLOW_MISSING_LANDLOCK=1."
  echo "Expect the filesystem cases of the test suite to fail."
else
  echo "Kernel does not list the Landlock security module in" >&2
  echo "/sys/kernel/security/lsm. The policy sets Landlock to best effort, so" >&2
  echo "the filesystem policy may not be enforced on this kernel." >&2
  echo "Set ALLOW_MISSING_LANDLOCK=1 to continue and measure the result." >&2
  exit 1
fi

echo "== 3/7 start the recipe-owned inference server =="
compose up -d --wait ollama
state_add compose ollama

echo "== 4/7 make the model available =="
if compose exec -T ollama ollama show "${INFERENCE_MODEL}" >/dev/null 2>&1; then
  echo "Model ${INFERENCE_MODEL} is already in the recipe volume."
else
  echo "Downloading model ${INFERENCE_MODEL} into the recipe volume."
  compose exec -T ollama ollama pull "${INFERENCE_MODEL}"
fi

echo "== 5/7 register the local server as an OpenShell provider =="
# OpenShell 0.1 has no gateway-wide inference route. The sandbox calls the
# Ollama server directly, and the attached provider's profile is what permits
# that one endpoint. The provider carries no credential: Ollama checks none.
if openshell profile describe "${PROFILE_ID}" >/dev/null 2>&1; then
  state_has profile "${PROFILE_ID}" || {
    echo "Provider profile ${PROFILE_ID} exists and this recipe did not import it." >&2
    echo "Inspect it with 'openshell profile describe ${PROFILE_ID}'." >&2
    exit 1
  }
  echo "Reusing provider profile ${PROFILE_ID}. Run scripts/teardown.sh to import a changed file."
else
  openshell profile lint -f "${PROFILE_FILE}"
  openshell profile import -f "${PROFILE_FILE}"
  state_add profile "${PROFILE_ID}"
fi
if openshell provider get "${INFERENCE_PROVIDER_NAME}" >/dev/null 2>&1; then
  state_has provider "${INFERENCE_PROVIDER_NAME}" || {
    echo "Provider ${INFERENCE_PROVIDER_NAME} exists and this recipe did not create it." >&2
    echo "Set INFERENCE_PROVIDER_NAME to an unused name, then run this script again." >&2
    exit 1
  }
  echo "Reusing provider ${INFERENCE_PROVIDER_NAME}."
else
  openshell provider create --name "${INFERENCE_PROVIDER_NAME}" --type "${PROFILE_ID}"
  state_add provider "${INFERENCE_PROVIDER_NAME}"
fi

echo "== 6/7 build the sandbox image and create the dedicated sandbox =="
if [[ "$(sandbox_phase)" != "Missing" ]] && ! state_has sandbox "${SANDBOX_NAME}"; then
  echo "Sandbox ${SANDBOX_NAME} exists and this recipe did not create it." >&2
  echo "Setup replaces the sandbox policy, so it does not reuse that sandbox." >&2
  echo "Set SANDBOX_NAME to an unused name, then run this script again." >&2
  exit 1
elif sandbox_is_ready; then
  echo "Reusing sandbox ${SANDBOX_NAME}."
elif [[ "$(sandbox_phase)" != "Missing" ]]; then
  echo "Sandbox ${SANDBOX_NAME} exists in phase '$(sandbox_phase)'." >&2
  echo "Wait for it, or run scripts/teardown.sh, then run this script again." >&2
  exit 1
else
  # OpenShell 0.1 creates a sandbox from an image, not from a Dockerfile.
  docker build \
    --build-arg "INFERENCE_MODEL=${INFERENCE_MODEL}" \
    --build-arg "INFERENCE_BASE_URL=${INFERENCE_BASE_URL}" \
    -t "${SANDBOX_IMAGE}" "${EXAMPLE_DIR}"
  state_add image "${SANDBOX_IMAGE}"
  create_log="${RUN_DIR}/sandbox-create.log"
  state_add sandbox "${SANDBOX_NAME}"
  openshell sandbox create \
    --name "${SANDBOX_NAME}" \
    --from "${SANDBOX_IMAGE}" \
    --policy "${POLICY_FILE}" \
    --provider "${INFERENCE_PROVIDER_NAME}" \
    --no-auto-providers \
    --env "OPENAI_BASE_URL=${INFERENCE_BASE_URL}" \
    --env "INFERENCE_MODEL=${INFERENCE_MODEL}" \
    --detach --no-tty >"${create_log}" 2>&1 </dev/null || {
    echo "Sandbox creation failed. See ${create_log}." >&2
    tail -n 20 "${create_log}" >&2
    exit 1
  }
  ready=0
  for _ in $(seq 1 240); do
    if sandbox_is_ready; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "${ready}" != 1 ]]; then
    echo "Sandbox did not become ready in 8 minutes. See ${create_log}." >&2
    exit 1
  fi
fi

# Apply the policy again and read back the effective policy: the sandbox
# policy plus the provider layer. A policy that cannot be read back is not
# accepted.
openshell policy set --policy "${POLICY_FILE}" --wait "${SANDBOX_NAME}"
openshell policy get "${SANDBOX_NAME}" --full -o json | localonly check-effective-policy

echo "== 7/7 copy the approved folder and the skill =="
sandbox_exec mkdir -p "${SANDBOX_WORKSPACE}" "${SANDBOX_SKILL_DIR}"
while IFS=$'\t' read -r relative source; do
  [[ -n "${relative}" ]] || continue
  parent="$(dirname "${relative}")"
  if [[ "${parent}" != "." ]]; then
    sandbox_exec mkdir -p "${SANDBOX_WORKSPACE}/${parent}"
  fi
  sandbox_copy "${source}" "${SANDBOX_WORKSPACE}/${relative}"
done <"${RUN_DIR}/workspace-files.tsv"
sandbox_copy "${EXAMPLE_DIR}/src/SKILL.md" "${SANDBOX_SKILL_DIR}/SKILL.md"

echo "Bring-up complete."
echo "Run the denied-action test suite with: bash scripts/verify.sh --live"
