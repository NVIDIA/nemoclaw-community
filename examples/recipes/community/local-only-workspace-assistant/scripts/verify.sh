#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Without arguments: run the static checks. They start no service, contact no
# external system, and leave nothing running.
#
# With --live: run the denied-action test suite against the running sandbox.
# The suite stops and restarts the recipe-owned inference server once.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${DIR}/_lib.sh"

live=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) live=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--live]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

load_env
require_command python3

if [[ "${live}" == 1 ]]; then
  require_command openshell
  require_command docker
  sandbox_is_ready || {
    echo "Sandbox ${SANDBOX_NAME} is not ready. Run scripts/bring-up.sh first." >&2
    exit 1
  }
  echo "== 1/3 effective sandbox policy (sandbox policy plus provider layer) =="
  openshell policy get "${SANDBOX_NAME}" --full -o json | localonly check-effective-policy

  echo "== 2/3 denied-action test suite =="
  evidence="${RUN_DIR}/evidence/conformance-$(date -u +%Y%m%dT%H%M%SZ).jsonl"
  run_args=(--sandbox "${SANDBOX_NAME}" --evidence "${evidence}")
  while IFS= read -r compose_file; do
    run_args+=(--compose-file "${compose_file}")
  done < <(compose_file_args)
  if host_is_wsl2; then
    run_args+=(--host-trait wsl2)
  else
    echo "Host is not WSL2. The cases that test Windows drives are not applicable."
  fi
  suite_status=0
  localonly run "${run_args[@]}" || suite_status=$?

  echo "== 3/3 where the model is loaded =="
  # Ollama can serve from the CPU without an error. Show the placement so the
  # operator can confirm that the GPU serves the model.
  compose exec -T ollama ollama ps || true

  if [[ "${suite_status}" != 0 ]]; then
    echo "FAIL: local-only-workspace-assistant live verification (status ${suite_status})" >&2
    exit "${suite_status}"
  fi
  echo "PASS: local-only-workspace-assistant live verification"
  exit 0
fi

skipped=0

echo "== 1/5 shell syntax =="
bash -n "${EXAMPLE_DIR}"/scripts/*.sh

echo "== 2/5 python syntax =="
python3 -m py_compile "${EXAMPLE_DIR}"/src/localonly/*.py "${EXAMPLE_DIR}"/src/tests/*.py

echo "== 3/5 unit tests =="
PYTHONPATH="${EXAMPLE_DIR}/src" python3 -m unittest discover \
  -s "${EXAMPLE_DIR}/src/tests" -t "${EXAMPLE_DIR}/src" -p 'test_*.py'

echo "== 4/5 policy, provider profile, endpoint, and approved folder =="
localonly check-policy "${POLICY_FILE}"
localonly check-profile "${PROFILE_FILE}" --base-url "${INFERENCE_BASE_URL}"
localonly check-publish-host "${OLLAMA_PUBLISH_HOST}"
localonly check-endpoint "${INFERENCE_BASE_URL}" --extra-hosts "${LOCAL_ENDPOINT_EXTRA_HOSTS}"
localonly list-workspace "${WORKSPACE_DIR}" \
  --max-file-bytes "${WORKSPACE_MAX_FILE_BYTES}" >/dev/null

echo "== 5/5 compose rendering =="
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f "${COMPOSE_FILE}" config >/dev/null
  docker compose -f "${COMPOSE_FILE}" -f "${COMPOSE_GPU_FILE}" config >/dev/null
else
  echo "SKIP: Docker Compose not found; docker-compose.yml was not rendered."
  skipped=$((skipped + 1))
fi

echo "PASS: local-only-workspace-assistant static verification (${skipped} skipped)"
