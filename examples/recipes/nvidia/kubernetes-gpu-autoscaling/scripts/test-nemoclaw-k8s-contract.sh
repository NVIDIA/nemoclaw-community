#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${CHART_DIR}/../../../.." && pwd)"
# shellcheck source=../../../../../scripts/example_dependencies.sh
source "${REPO_ROOT}/scripts/example_dependencies.sh"
load_example_dependencies "${CHART_DIR}"

[[ "${NEMOCLAW_INSTALL_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "${NEMOCLAW_AGENT}" == "openclaw" ]]
[[ "${NEMOCLAW_INSTALL_REF}" =~ ^[0-9a-f]{40}$ ]]
[[ "${OPENSHELL_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "${AGENT_SANDBOX_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]

BUILD_SCRIPT="${SCRIPT_DIR}/build-nemoclaw-sandbox-image.sh"
INSTALL_SCRIPT="${SCRIPT_DIR}/install-openshell-k8s.sh"
CREATE_SCRIPT="${SCRIPT_DIR}/create-nemoclaw-sandbox.sh"
RUN_SCRIPT="${SCRIPT_DIR}/run-nemoclaw-sandbox.sh"
# shellcheck source=hpa-common.sh
source "${SCRIPT_DIR}/hpa-common.sh"

grep -Fq 'NEMOCLAW_MANAGED_IMAGE_CAPABILITY_UNION=0' "${BUILD_SCRIPT}"
grep -Fq 'ACTUAL_NEMOCLAW_COMMIT' "${BUILD_SCRIPT}"
grep -Fq 'NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1' "${BUILD_SCRIPT}"
grep -Fq -- '--set "server.auth.allowUnauthenticatedUsers=${UNAUTHENTICATED_VALUE}"' "${INSTALL_SCRIPT}"
if grep -Fq -- '--set-string "server.auth.allowUnauthenticatedUsers=' "${INSTALL_SCRIPT}"; then
  echo "FAIL: OpenShell unauthenticated-user policy must be a Helm boolean, not a truthy string" >&2
  exit 1
fi
grep -Fq 'service.type=ClusterIP' "${INSTALL_SCRIPT}"
grep -Fq 'kubectl get crd sandboxes.agents.x-k8s.io' "${INSTALL_SCRIPT}"
grep -Fq 'hpa_common_verify_target_node 1' "${INSTALL_SCRIPT}"
grep -Fq 'hpa_common_verify_target_node 1' "${CREATE_SCRIPT}"
grep -Fq 'hpa_common_target_node_helm_value' "${INSTALL_SCRIPT}"
grep -Fq "'tolerations[0].key=nvidia.com/gpu'" "${INSTALL_SCRIPT}"
grep -Fq -- '--credential OPENAI_API_KEY' "${CREATE_SCRIPT}"
grep -Fq 'hpa_common_inference_secret_contract' "${CREATE_SCRIPT}"
grep -Fq 'hpa_common_inference_secret_contract' "${SCRIPT_DIR}/hpa-load-test.sh"
grep -Fq 'ACTUAL_NEMOCLAW_COMMIT' "${CREATE_SCRIPT}"
grep -Fq -- '--policy "${POLICY_FILE}"' "${CREATE_SCRIPT}"
grep -Fq -- '--remove-endpoint integrate.api.nvidia.com:443' "${CREATE_SCRIPT}"
grep -Fq 'effective sandbox policy still permits NVIDIA-hosted inference' "${CREATE_SCRIPT}"
grep -Fq -- '-- /bin/true' "${CREATE_SCRIPT}"
grep -Fq -- '--driver-config-json "${DRIVER_CONFIG_JSON}"' "${CREATE_SCRIPT}"
grep -Fq '"node_selector": {"kubernetes.io/hostname": sys.argv[1]}' "${CREATE_SCRIPT}"
grep -Fq '"key": "nvidia.com/gpu"' "${CREATE_SCRIPT}"
grep -Fq 'hpa_common_openshell_inference_base_url' "${CREATE_SCRIPT}"
grep -Fq 'OpenShell → Envoy Gateway (LeastRequest)' "${CREATE_SCRIPT}"
grep -Fq 'Envoy LB disabled' "${CREATE_SCRIPT}"
grep -Fq -- '--no-tty -- /bin/true' "${CREATE_SCRIPT}"
grep -Fq 'curl -fsS https://inference.local/v1/models' "${CREATE_SCRIPT}"
grep -Fq 'curl -fsS https://inference.local/v1/chat/completions' "${CREATE_SCRIPT}"
grep -Fq 'ENABLE_ENVOY_LB' "${SCRIPT_DIR}/install-hpa.sh"
grep -Fq 'ingress.gateway.enabled' "${SCRIPT_DIR}/hpa-common.sh"
grep -Fq 'umask 022' "${BUILD_SCRIPT}"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify-nemoclaw-sandbox.sh"
[[ -x "${VERIFY_SCRIPT}" ]] || { echo "FAIL: verify-nemoclaw-sandbox.sh missing or not executable" >&2; exit 1; }
grep -Fq 'https://inference.local/v1/chat/completions' "${VERIFY_SCRIPT}"
grep -Fq 'exec openshell sandbox exec' "${RUN_SCRIPT}"
grep -Fq '/usr/local/bin/nemoclaw-start' "${RUN_SCRIPT}"

if grep -Eq 'NVIDIA_API_KEY' \
  "${BUILD_SCRIPT}" "${INSTALL_SCRIPT}" "${CREATE_SCRIPT}" "${RUN_SCRIPT}"; then
  echo "FAIL: native Kubernetes path contains a cloud inference API key" >&2
  exit 1
fi
if grep -Fq 'integrate.api.nvidia.com' \
  "${BUILD_SCRIPT}" "${INSTALL_SCRIPT}" "${RUN_SCRIPT}"; then
  echo "FAIL: native Kubernetes path configures a cloud inference endpoint" >&2
  exit 1
fi
if grep -Fq -- '--gpu' "${CREATE_SCRIPT}"; then
  echo "FAIL: NemoClaw sandbox must not request a GPU" >&2
  exit 1
fi

helm() {
  printf '%s\n' '{"inference":{"auth":{"existingSecret":"operator-inference-api.gpu-platform.production.cluster.example.internal","key":"true"}}}'
}
SECRET_CONTRACT="$(
  hpa_common_inference_secret_contract \
    test-namespace test-release test-release-metrics-proxy-inference-api
)"
if [[ "${SECRET_CONTRACT}" != $'operator-inference-api.gpu-platform.production.cluster.example.internal\ttrue' ]]; then
  echo "FAIL: scripts do not resolve the operator-managed inference Secret contract" >&2
  exit 1
fi

echo "OK: experimental NemoClaw Kubernetes path uses authenticated on-prem inference"
