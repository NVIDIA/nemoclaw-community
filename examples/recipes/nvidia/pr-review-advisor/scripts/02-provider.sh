#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

validate_only=0
lock_held=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --validate-only) validate_only=1 ;;
    --lock-held) lock_held=1 ;;
    *)
      echo "Usage: $(basename "$0") [--validate-only] [--lock-held]" >&2
      exit 2
      ;;
  esac
  shift
done

ambient_nvidia_set=0
ambient_compatible_set=0
ambient_nvidia=""
ambient_compatible=""
if [[ "${NVIDIA_INFERENCE_API_KEY+x}" == x \
    && -n "${NVIDIA_INFERENCE_API_KEY:-}" ]]; then
  ambient_nvidia_set=1
  ambient_nvidia="$NVIDIA_INFERENCE_API_KEY"
fi
if [[ "${COMPATIBLE_API_KEY+x}" == x && -n "${COMPATIBLE_API_KEY:-}" ]]; then
  ambient_compatible_set=1
  ambient_compatible="$COMPATIBLE_API_KEY"
fi

scrub_external_secrets
load_env --provider-credentials
require_command openshell
validate_name "$INFERENCE_PROVIDER_NAME"

if [[ "$lock_held" == 1 ]]; then
  [[ "${REVIEW_ADVISOR_LOCK_DIR:-}" == "${STATE_DIR}/review.lock" \
      && -d "$REVIEW_ADVISOR_LOCK_DIR" ]] || {
    echo "--lock-held requires the inherited lifecycle lock" >&2
    exit 2
  }
else
  acquire_review_lock
  trap release_review_lock EXIT INT TERM
fi

assert_gateway_identity
settings="$(run_openshell settings get --global --json)"
(( ${#settings} <= 65536 )) || {
  echo "OpenShell settings output exceeded 65536 bytes" >&2
  exit 1
}
if ! python3 - "$settings" <<'PY'
import json
import sys

try:
    value = json.loads(sys.argv[1])
except json.JSONDecodeError as error:
    raise SystemExit(f"OpenShell settings returned invalid JSON: {error}")
if (
    not isinstance(value, dict)
    or not isinstance(value.get("scope"), str)
    or not isinstance(value.get("settings_revision"), int)
    or not isinstance(value.get("settings"), dict)
    or value["settings"].get("providers_v2_enabled") != "true"
):
    raise SystemExit(1)
PY
then
  echo "OpenShell provider v2 is disabled. Enable it with:" >&2
  echo "  openshell settings set --global --key providers_v2_enabled --value true --yes" >&2
  exit 1
fi

file_nvidia="${NVIDIA_INFERENCE_API_KEY:-}"
file_compatible="${COMPATIBLE_API_KEY:-}"
if [[ -n "$file_nvidia" && "$ambient_nvidia_set" == 1 ]]; then
  echo "NVIDIA_INFERENCE_API_KEY is set in both .env and the process environment" >&2
  exit 1
fi
if [[ -n "$file_compatible" && "$ambient_compatible_set" == 1 ]]; then
  echo "COMPATIBLE_API_KEY is set in both .env and the process environment" >&2
  exit 1
fi

provider_key=""
provider_type=""
credential_env=""
config_key=""
case "$REVIEW_ADVISOR_PROVIDER_MODE" in
  nvidia)
    provider_type="nvidia"
    credential_env="NVIDIA_API_KEY"
    config_key="NVIDIA_BASE_URL"
    if [[ -n "$file_compatible" || "$ambient_compatible_set" == 1 ]]; then
      echo "nvidia mode forbids COMPATIBLE_API_KEY" >&2
      exit 1
    fi
    if [[ -n "$file_nvidia" ]]; then
      provider_key="$file_nvidia"
    elif [[ "$ambient_nvidia_set" == 1 ]]; then
      provider_key="$ambient_nvidia"
    fi
    ;;
  openai-compatible)
    provider_type="openai"
    credential_env="OPENAI_API_KEY"
    config_key="OPENAI_BASE_URL"
    if [[ -n "$file_nvidia" || "$ambient_nvidia_set" == 1 ]]; then
      echo "openai-compatible mode forbids NVIDIA_INFERENCE_API_KEY" >&2
      exit 1
    fi
    if [[ -n "$file_compatible" ]]; then
      provider_key="$file_compatible"
    elif [[ "$ambient_compatible_set" == 1 ]]; then
      provider_key="$ambient_compatible"
    fi
    ;;
  existing)
    provider_type="$REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE"
    case "$provider_type" in
      nvidia|openai|deepinfra) ;;
      *)
        echo "existing mode supports only reviewed inference provider types: nvidia, openai, deepinfra" >&2
        exit 1
        ;;
    esac
    if [[ -n "$file_nvidia" || -n "$file_compatible" \
        || "$ambient_nvidia_set" == 1 || "$ambient_compatible_set" == 1 ]]; then
      echo "existing mode forbids managed inference credentials" >&2
      exit 1
    fi
    ;;
esac

ambient_nvidia=""
ambient_compatible=""
file_nvidia=""
file_compatible=""
unset NVIDIA_INFERENCE_API_KEY COMPATIBLE_API_KEY
scrub_external_secrets

set +e
provider_exists
provider_status=$?
set -e
case "$provider_status" in
  0) ;;
  1)
    if [[ "$validate_only" == 1 || "$REVIEW_ADVISOR_PROVIDER_MODE" == "existing" ]]; then
      echo "Required OpenShell provider is not registered: $INFERENCE_PROVIDER_NAME" >&2
      exit 1
    fi
    ;;
  *)
    echo "Could not inspect OpenShell provider metadata" >&2
    exit 1
    ;;
esac

if [[ "$validate_only" == 1 ]]; then
  if [[ "$REVIEW_ADVISOR_PROVIDER_MODE" == "existing" ]]; then
    assert_provider_metadata "$provider_type"
  else
    assert_provider_metadata "$provider_type" "$credential_env" "$config_key"
  fi
  assert_inference_route
  echo "Inference validation passed: provider=$INFERENCE_PROVIDER_NAME model=$NEMOCLAW_MODEL"
  exit 0
fi

if [[ "$REVIEW_ADVISOR_PROVIDER_MODE" != "existing" ]]; then
  [[ -n "$provider_key" ]] || {
    if [[ "$REVIEW_ADVISOR_PROVIDER_MODE" == "nvidia" ]]; then
      echo "Set exactly NVIDIA_INFERENCE_API_KEY in ${INSTALL_DIR}/.env or the process environment" >&2
    else
      echo "Set exactly COMPATIBLE_API_KEY in ${INSTALL_DIR}/.env or the process environment" >&2
    fi
    exit 1
  }
  if (( ${#provider_key} > 8192 )) || [[ "$provider_key" =~ [[:cntrl:]] ]]; then
    echo "Inference credential must be at most 8192 characters without control characters" >&2
    exit 1
  fi
  if [[ "$provider_status" == 0 ]]; then
    assert_provider_metadata "$provider_type"
    (
      export "${credential_env}=${provider_key}"
      run_openshell provider update "$INFERENCE_PROVIDER_NAME" \
        --credential "$credential_env" \
        --config "${config_key}=${NEMOCLAW_ENDPOINT_URL}"
    )
  else
    (
      export "${credential_env}=${provider_key}"
      run_openshell provider create \
        --name "$INFERENCE_PROVIDER_NAME" \
        --type "$provider_type" \
        --credential "$credential_env" \
        --config "${config_key}=${NEMOCLAW_ENDPOINT_URL}"
    )
  fi
  provider_key=""
  unset provider_key
  scrub_external_secrets
  assert_provider_metadata "$provider_type" "$credential_env" "$config_key"
else
  # Existing mode validates metadata and deliberately never changes credentials.
  assert_provider_metadata "$provider_type"
fi

# This route is gateway-wide, which is why 01-gateway.sh requires an endpoint
# dedicated to this installation and every command resolves it by exact name.
run_openshell inference set \
  --provider "$INFERENCE_PROVIDER_NAME" \
  --model "$NEMOCLAW_MODEL"
assert_inference_route
echo "Inference ready: provider=$INFERENCE_PROVIDER_NAME model=$NEMOCLAW_MODEL"
