#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Verify an existing CPU-only NemoClaw sandbox can reach on-premises inference
# through OpenShell's https://inference.local route (Envoy LeastRequest when enabled).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${CHART_DIR}/../../../.." && pwd)"
# shellcheck source=../../../../../scripts/example_dependencies.sh
source "${REPO_ROOT}/scripts/example_dependencies.sh"
load_example_dependencies "${CHART_DIR}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "[verify] $*"
}

command -v openshell >/dev/null 2>&1 || fail "missing command: openshell"
command -v python3 >/dev/null 2>&1 || fail "missing command: python3"
command -v timeout >/dev/null 2>&1 || fail "missing command: timeout"

require_example_dependency_version \
  "OpenShell CLI" "${OPENSHELL_VERSION}" openshell --version

SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-nemoclaw-onprem}"
MODEL="${INFERENCE_MODEL:-llama3.2:3b}"
# openclaw plugins inspect can hang on a cold/busy gateway; keep it short.
PLUGIN_TIMEOUT_SEC="${VERIFY_PLUGIN_TIMEOUT_SEC:-60}"
CURL_TIMEOUT_SEC="${VERIFY_CURL_TIMEOUT_SEC:-120}"

sandbox_exec() {
  local timeout_sec="${1:?timeout}"
  shift
  timeout --foreground "${timeout_sec}" openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty -- "$@"
}

log "Checking OpenShell gateway connection..."
openshell status >/dev/null \
  || fail "OpenShell gateway is not connected; port-forward service/openshell and re-register the gateway"

log "Checking sandbox ${SANDBOX_NAME}..."
openshell sandbox get "${SANDBOX_NAME}" >/dev/null 2>&1 \
  || fail "sandbox ${SANDBOX_NAME} does not exist; run create-nemoclaw-sandbox.sh first"

log "Checking sandbox policy does not allow NVIDIA-hosted inference..."
EFFECTIVE_POLICY="$(openshell policy get "${SANDBOX_NAME}" --full -o json)"
if grep -Fq 'integrate.api.nvidia.com' <<<"${EFFECTIVE_POLICY}"; then
  fail "effective sandbox policy still permits NVIDIA-hosted inference"
fi
unset EFFECTIVE_POLICY

log "Inspecting nemoclaw plugin (timeout ${PLUGIN_TIMEOUT_SEC}s)..."
if ! sandbox_exec "${PLUGIN_TIMEOUT_SEC}" \
  openclaw plugins inspect nemoclaw --json >/dev/null; then
  fail "openclaw plugins inspect nemoclaw timed out or failed after ${PLUGIN_TIMEOUT_SEC}s"
fi
log "Plugin inspect OK."

log "GET https://inference.local/v1/models (timeout ${CURL_TIMEOUT_SEC}s)..."
MODELS_JSON="$(
  sandbox_exec "${CURL_TIMEOUT_SEC}" \
    curl -fsS --max-time "${CURL_TIMEOUT_SEC}" https://inference.local/v1/models
)" || fail "GET /v1/models timed out or failed after ${CURL_TIMEOUT_SEC}s"
python3 -c 'import json,sys; expected=sys.argv[1]; payload=json.loads(sys.argv[2]); ids=[item.get("id") for item in payload.get("data") or []];
assert expected in ids, f"inference.local /v1/models missing {expected!r}; got {ids!r}";
print("models:", ", ".join(ids))' \
  "${MODEL}" "${MODELS_JSON}"

QUERY='In one sentence, what is an AI agent sandbox?'
log "POST https://inference.local/v1/chat/completions"
log "Example query: ${QUERY}"
CHAT_JSON="$(
  sandbox_exec "${CURL_TIMEOUT_SEC}" \
    curl -fsS --max-time "${CURL_TIMEOUT_SEC}" https://inference.local/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"${QUERY}\"}],\"max_tokens\":256,\"stream\":false}"
)" || fail "POST /v1/chat/completions timed out or failed after ${CURL_TIMEOUT_SEC}s"
ANSWER="$(
  python3 -c 'import json,sys; payload=json.loads(sys.argv[1]); choices=payload.get("choices") or [];
assert choices, f"chat/completions returned no choices: {payload!r}";
content=((choices[0].get("message") or {}).get("content") or "").strip();
assert content, "chat/completions returned an empty assistant message";
print(content)' "${CHAT_JSON}"
)"
log "Answer: ${ANSWER}"

echo "OK: sandbox ${SANDBOX_NAME} reached https://inference.local for models and chat/completions (${MODEL})."
echo "Runtime (optional foreground): ./scripts/run-nemoclaw-sandbox.sh"
