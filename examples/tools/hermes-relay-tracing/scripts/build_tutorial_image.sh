#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1090
source "$repo_root/config/smoke.env"
image_name="$SMOKE_DOCKER_IMAGE"

command -v docker >/dev/null || {
  echo "Docker is required to build the tutorial terminal image." >&2
  exit 1
}

docker build --tag "$image_name" --file "$repo_root/Dockerfile" "$repo_root"
