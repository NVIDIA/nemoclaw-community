#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$repo_root/config/phoenix.env"

command -v docker >/dev/null || {
  echo "Docker is required to remove the tutorial Phoenix container." >&2
  exit 1
}

ownership_label="com.nvidia.nemoclaw-community.hermes-relay-tracing.component"
container_id="$(docker ps -aq --filter "name=^/${PHOENIX_CONTAINER_NAME}$")"
if [[ -z "$container_id" ]]; then
  echo "The tutorial Phoenix container is not present."
  exit 0
fi

actual_owner="$(docker inspect --format "{{ index .Config.Labels \"$ownership_label\" }}" "$container_id")"
if [[ "$actual_owner" != "phoenix" ]]; then
  echo "Refusing to remove $PHOENIX_CONTAINER_NAME because it is not owned by this tutorial." >&2
  exit 1
fi

docker rm --force "$container_id" >/dev/null
echo "Removed the tutorial Phoenix container."
