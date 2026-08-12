#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Configure OpenShell's gateway-scoped inference route through Envoy Gateway
# (LeastRequest) when ENABLE_ENVOY_LB=1 / a Gateway exists, otherwise through the
# metrics-proxy Service, then create a NemoClaw/OpenClaw sandbox without assigning it a GPU.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../versions.env
source "${CHART_DIR}/versions.env"
# shellcheck source=hpa-common.sh
source "${SCRIPT_DIR}/hpa-common.sh"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_cmd git
require_cmd helm
require_cmd kubectl
require_cmd openshell
require_cmd python3

SANDBOX_IMAGE="${NEMOCLAW_SANDBOX_IMAGE:-}"
SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-nemoclaw-onprem}"
INFERENCE_NAMESPACE="${NAMESPACE:-nemoclaw-gpu}"
INFERENCE_RELEASE="${RELEASE:-nemoclaw-gpu}"
INFERENCE_SERVICE="${INFERENCE_SERVICE:-${INFERENCE_RELEASE}-metrics-proxy}"
INFERENCE_PORT="${SERVICE_PORT:-8081}"
MODEL="${INFERENCE_MODEL:-llama3.2:3b}"
PROVIDER_NAME="${OPENSHELL_PROVIDER_NAME:-onprem-ollama}"
IMAGE_NAME="${SANDBOX_IMAGE##*/}"

[[ -n "${SANDBOX_IMAGE}" ]] || fail "set NEMOCLAW_SANDBOX_IMAGE to the pushed image"
[[ "${SANDBOX_IMAGE}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/@-]+$ ]] \
  || fail "NEMOCLAW_SANDBOX_IMAGE contains unsupported characters"
if [[ "${SANDBOX_IMAGE}" == *@* ]]; then
  [[ "${SANDBOX_IMAGE}" =~ @sha256:[0-9a-f]{64}$ ]] \
    || fail "NEMOCLAW_SANDBOX_IMAGE contains an invalid digest"
else
  [[ "${IMAGE_NAME}" == *:* && "${SANDBOX_IMAGE}" != *:latest ]] \
    || fail "NEMOCLAW_SANDBOX_IMAGE must use a non-latest tag or an image digest"
fi
[[ "${INFERENCE_NAMESPACE}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
  || fail "NAMESPACE must be a valid lowercase Kubernetes namespace"
[[ "${INFERENCE_SERVICE}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
  || fail "INFERENCE_SERVICE must be a valid lowercase Kubernetes Service name"
if [[ ! "${INFERENCE_PORT}" =~ ^[0-9]+$ ]] \
  || ((10#${INFERENCE_PORT} < 1 || 10#${INFERENCE_PORT} > 65535)); then
  fail "SERVICE_PORT must be an integer from 1 to 65535"
fi
[[ "${MODEL}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || fail "INFERENCE_MODEL is invalid"
[[ "${PROVIDER_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || fail "OPENSHELL_PROVIDER_NAME is invalid"
[[ "${SANDBOX_NAME}" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] \
  || fail "NEMOCLAW_SANDBOX_NAME must be a 2-63 character lowercase Kubernetes-style name"
hpa_common_verify_target_node 1 || exit 1

ACTUAL_OPENSHELL_VERSION="$(openshell --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)"
[[ "${ACTUAL_OPENSHELL_VERSION}" == "${OPENSHELL_VERSION}" ]] \
  || fail "OpenShell CLI ${OPENSHELL_VERSION} is required; found ${ACTUAL_OPENSHELL_VERSION:-unknown}"
openshell status >/dev/null

IFS=$'\t' read -r DEPLOYED_INFERENCE_SECRET DEPLOYED_INFERENCE_SECRET_KEY < <(
  hpa_common_inference_secret_contract \
    "${INFERENCE_NAMESPACE}" "${INFERENCE_RELEASE}" "${INFERENCE_SERVICE}-inference-api"
)
INFERENCE_SECRET="${INFERENCE_API_SECRET:-${DEPLOYED_INFERENCE_SECRET}}"
INFERENCE_SECRET_KEY="${INFERENCE_API_SECRET_KEY:-${DEPLOYED_INFERENCE_SECRET_KEY}}"
[[ "${INFERENCE_SECRET}" =~ ^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$ ]] \
  || fail "INFERENCE_API_SECRET is not a valid Kubernetes Secret name"
[[ "${INFERENCE_SECRET_KEY}" =~ ^[A-Za-z0-9._-]+$ ]] \
  || fail "INFERENCE_API_SECRET_KEY is invalid"

SOURCE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${SOURCE_ROOT}"' EXIT
git clone --quiet --depth 1 --branch "${NEMOCLAW_VERSION}" \
  https://github.com/NVIDIA/NemoClaw.git "${SOURCE_ROOT}/nemoclaw"
ACTUAL_NEMOCLAW_COMMIT="$(git -C "${SOURCE_ROOT}/nemoclaw" rev-parse HEAD)"
[[ "${ACTUAL_NEMOCLAW_COMMIT}" == "${NEMOCLAW_COMMIT}" ]] \
  || fail "NemoClaw ${NEMOCLAW_VERSION} resolved to unexpected commit ${ACTUAL_NEMOCLAW_COMMIT}"
POLICY_FILE="${SOURCE_ROOT}/nemoclaw/nemoclaw-blueprint/policies/openclaw-sandbox.yaml"
[[ -f "${POLICY_FILE}" ]] || fail "NemoClaw release policy is missing"

API_KEY="$(
  kubectl get secret "${INFERENCE_SECRET}" -n "${INFERENCE_NAMESPACE}" -o json \
    | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["data"][sys.argv[1]]).decode())' \
      "${INFERENCE_SECRET_KEY}"
)"
[[ -n "${API_KEY}" ]] || fail "inference API key is empty"

BASE_URL="$(
  hpa_common_openshell_inference_base_url \
    "${INFERENCE_NAMESPACE}" \
    "${INFERENCE_RELEASE}-metrics-proxy" \
    "${INFERENCE_SERVICE}" \
    "${INFERENCE_PORT}"
)"
[[ "${BASE_URL}" =~ ^https?://.+/v1$ ]] \
  || fail "resolved OpenShell inference base URL is invalid: ${BASE_URL}"
if openshell provider get "${PROVIDER_NAME}" >/dev/null 2>&1; then
  OPENAI_API_KEY="${API_KEY}" openshell provider update "${PROVIDER_NAME}" \
    --credential OPENAI_API_KEY \
    --config "OPENAI_BASE_URL=${BASE_URL}"
else
  OPENAI_API_KEY="${API_KEY}" openshell provider create \
    --name "${PROVIDER_NAME}" \
    --type openai \
    --credential OPENAI_API_KEY \
    --config "OPENAI_BASE_URL=${BASE_URL}"
fi
unset API_KEY

openshell inference set \
  --provider "${PROVIDER_NAME}" \
  --model "${MODEL}" \
  --timeout 300

if openshell sandbox get "${SANDBOX_NAME}" >/dev/null 2>&1; then
  fail "sandbox ${SANDBOX_NAME} already exists; choose another name or delete it explicitly"
fi

SANDBOX_CREATE_ARGS=(
  --name "${SANDBOX_NAME}"
  --from "${SANDBOX_IMAGE}"
  --policy "${POLICY_FILE}"
  --cpu "${NEMOCLAW_SANDBOX_CPU:-2}"
  --memory "${NEMOCLAW_SANDBOX_MEMORY:-4Gi}"
)
if [[ -n "${NEMOCLAW_TARGET_NODE:-}" ]]; then
  DRIVER_CONFIG_JSON="$(python3 - "${NEMOCLAW_TARGET_NODE}" <<'PYEOF'
import json
import sys

print(json.dumps({
    "kubernetes": {
        "pod": {
            "node_selector": {"kubernetes.io/hostname": sys.argv[1]},
            "tolerations": [{
                "key": "nvidia.com/gpu",
                "operator": "Exists",
                "effect": "NoSchedule",
            }],
        },
    },
}))
PYEOF
)"
  SANDBOX_CREATE_ARGS+=(--driver-config-json "${DRIVER_CONFIG_JSON}")
fi

openshell sandbox create "${SANDBOX_CREATE_ARGS[@]}" --no-tty -- /bin/true

# The upstream NemoClaw base policy includes NVIDIA-hosted inference as a default
# endpoint. This recipe is on-premises-only, so remove that endpoint before the
# sandbox NemoClaw/OpenClaw AI agent starts, then verify the effective policy.
openshell policy update "${SANDBOX_NAME}" \
  --remove-endpoint integrate.api.nvidia.com:443 \
  --wait \
  --timeout 60
EFFECTIVE_POLICY="$(openshell policy get "${SANDBOX_NAME}" --full -o json)"
if grep -Fq 'integrate.api.nvidia.com' <<<"${EFFECTIVE_POLICY}"; then
  fail "effective sandbox policy still permits NVIDIA-hosted inference"
fi
unset EFFECTIVE_POLICY

openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- \
  openclaw plugins inspect nemoclaw --json >/dev/null
openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- \
  curl -fsS https://inference.local/v1/models >/dev/null
# Example: ask a real question through OpenShell → Envoy (or metrics-proxy Service) → Ollama.
openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- \
  curl -fsS https://inference.local/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"In one sentence, what is an AI agent sandbox?\"}],\"max_tokens\":256,\"stream\":false}" \
  >/dev/null

echo "NemoClaw sandbox ${SANDBOX_NAME} is ready without a GPU."
if kubectl get gateway "${INFERENCE_RELEASE}-metrics-proxy" -n "${INFERENCE_NAMESPACE}" >/dev/null 2>&1; then
  echo "Inference routes through OpenShell → Envoy Gateway (LeastRequest) → ${BASE_URL}; only the Ollama HPA pods request GPUs."
else
  echo "Inference routes through OpenShell → metrics-proxy Service → ${BASE_URL} (Envoy LB disabled); only the Ollama HPA pods request GPUs."
fi
echo "Verify anytime: ./scripts/verify-nemoclaw-sandbox.sh"
echo "Start the NemoClaw/OpenClaw runtime in a dedicated terminal: ./scripts/run-nemoclaw-sandbox.sh"
