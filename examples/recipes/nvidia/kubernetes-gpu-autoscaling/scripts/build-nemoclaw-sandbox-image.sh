#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build a deployment-specific NemoClaw/OpenClaw image and push it to a registry that
# the remote OpenShell Kubernetes gateway can pull. No inference API key enters the image.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../versions.env
source "${CHART_DIR}/versions.env"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_cmd docker
require_cmd git
require_cmd sed

SANDBOX_IMAGE="${NEMOCLAW_SANDBOX_IMAGE:-}"
MODEL="${INFERENCE_MODEL:-llama3.2:3b}"
PLATFORM="${NEMOCLAW_IMAGE_PLATFORM:-linux/amd64}"
IMAGE_NAME="${SANDBOX_IMAGE##*/}"

[[ "${NEMOCLAW_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || fail "versions.env contains an invalid NEMOCLAW_VERSION"
[[ "${OPENSHELL_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || fail "versions.env contains an invalid OPENSHELL_VERSION"
[[ -n "${SANDBOX_IMAGE}" ]] \
  || fail "set NEMOCLAW_SANDBOX_IMAGE to a registry image with a non-latest tag"
[[ "${SANDBOX_IMAGE}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/@-]+$ ]] \
  || fail "NEMOCLAW_SANDBOX_IMAGE contains unsupported characters"
[[ "${SANDBOX_IMAGE}" == */* ]] \
  || fail "NEMOCLAW_SANDBOX_IMAGE must include a registry/repository path"
[[ "${SANDBOX_IMAGE}" != *@* && "${IMAGE_NAME}" == *:* ]] \
  || fail "NEMOCLAW_SANDBOX_IMAGE must be a tagged build target, not a digest"
[[ "${SANDBOX_IMAGE}" != *:latest ]] \
  || fail "NEMOCLAW_SANDBOX_IMAGE must not use the mutable latest tag"
[[ "${PLATFORM}" == "linux/amd64" || "${PLATFORM}" == "linux/arm64" ]] \
  || fail "NEMOCLAW_IMAGE_PLATFORM must be linux/amd64 or linux/arm64"
[[ "${MODEL}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || fail "INFERENCE_MODEL is invalid"

BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${BUILD_ROOT}"' EXIT
SOURCE_DIR="${BUILD_ROOT}/nemoclaw"

# Hosts with a shared-group umask (e.g. 002) check out files as 775/664; the
# NemoClaw Dockerfile metadata gate expects 755/644. Normalize before Buildx COPY.
umask 022

echo "Cloning NVIDIA/NemoClaw ${NEMOCLAW_VERSION}..."
git clone --quiet --depth 1 --branch "${NEMOCLAW_VERSION}" \
  https://github.com/NVIDIA/NemoClaw.git "${SOURCE_DIR}"
ACTUAL_NEMOCLAW_COMMIT="$(git -C "${SOURCE_DIR}" rev-parse HEAD)"
[[ "${ACTUAL_NEMOCLAW_COMMIT}" == "${NEMOCLAW_COMMIT}" ]] \
  || fail "NemoClaw ${NEMOCLAW_VERSION} resolved to unexpected commit ${ACTUAL_NEMOCLAW_COMMIT}"

find "${SOURCE_DIR}" -type d -exec chmod 755 {} +
find "${SOURCE_DIR}" -type f ! -perm /111 -exec chmod 644 {} +
find "${SOURCE_DIR}" -type f -perm /111 -exec chmod 755 {} +

BLUEPRINT="${SOURCE_DIR}/nemoclaw-blueprint/blueprint.yaml"
[[ -f "${BLUEPRINT}" ]] || fail "NemoClaw release is missing its blueprint"
BLUEPRINT_MIN="$(sed -nE 's/^min_openshell_version:[[:space:]]*"([0-9.]+)"/\1/p' "${BLUEPRINT}")"
BLUEPRINT_MAX="$(sed -nE 's/^max_openshell_version:[[:space:]]*"([0-9.]+)"/\1/p' "${BLUEPRINT}")"
[[ "${BLUEPRINT_MIN}" == "${OPENSHELL_VERSION}" && "${BLUEPRINT_MAX}" == "${OPENSHELL_VERSION}" ]] \
  || fail "NemoClaw ${NEMOCLAW_VERSION} requires OpenShell ${BLUEPRINT_MIN}-${BLUEPRINT_MAX}, not ${OPENSHELL_VERSION}"

echo "Building and pushing ${SANDBOX_IMAGE} for ${PLATFORM}..."
docker buildx build \
  --platform "${PLATFORM}" \
  --pull \
  --push \
  --provenance=true \
  --sbom=true \
  --tag "${SANDBOX_IMAGE}" \
  --build-arg "BASE_IMAGE=ghcr.io/nvidia/nemoclaw/sandbox-base:${NEMOCLAW_VERSION}" \
  --build-arg "NEMOCLAW_MODEL=${MODEL}" \
  --build-arg "NEMOCLAW_PRIMARY_MODEL_REF=inference/${MODEL}" \
  --build-arg "NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1" \
  --build-arg "NEMOCLAW_INFERENCE_API=openai-completions" \
  --build-arg "NEMOCLAW_MANAGED_IMAGE_CAPABILITY_UNION=0" \
  --build-arg "NEMOCLAW_MANAGED_IMAGE_RUNTIME_USER=root" \
  --build-arg "NEMOCLAW_BUILD_ID=kubernetes-onprem-${NEMOCLAW_VERSION}" \
  "${SOURCE_DIR}"

echo "Pushed deployment-specific NemoClaw sandbox image: ${SANDBOX_IMAGE}"
echo "The image contains no inference API key. OpenShell receives that key separately."
