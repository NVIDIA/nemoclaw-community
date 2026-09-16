#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$repo_root/config/phoenix.env"

command -v docker >/dev/null || {
  echo "Docker is required to run Example 2 in Phoenix." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "Docker is not running. Start Docker and try again." >&2
  exit 1
}
command -v curl >/dev/null || {
  echo "curl is required to check Phoenix readiness." >&2
  exit 1
}

ownership_label="com.nvidia.nemoclaw-community.hermes-relay-tracing.component"
container_id="$(docker ps -aq --filter "name=^/${PHOENIX_CONTAINER_NAME}$")"
if [[ -n "$container_id" ]]; then
  actual_owner="$(docker inspect --format "{{ index .Config.Labels \"$ownership_label\" }}" "$container_id")"
  actual_image="$(docker inspect --format '{{.Config.Image}}' "$container_id")"
  if [[ "$actual_owner" != "phoenix" || "$actual_image" != "$PHOENIX_IMAGE" ]]; then
    echo "Container $PHOENIX_CONTAINER_NAME already exists but is not the pinned tutorial container." >&2
    echo "Remove or rename that container before continuing." >&2
    exit 1
  fi
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != "true" ]]; then
    docker start "$container_id" >/dev/null
  fi
else
  if ! docker run --detach \
      --name "$PHOENIX_CONTAINER_NAME" \
      --label "$ownership_label=phoenix" \
      --publish "127.0.0.1:$PHOENIX_UI_PORT:6006" \
      --env PHOENIX_ALLOW_EXTERNAL_RESOURCES=false \
      "$PHOENIX_IMAGE" >/dev/null; then
    failed_id="$(docker ps -aq --filter "name=^/${PHOENIX_CONTAINER_NAME}$")"
    if [[ -n "$failed_id" ]] \
        && [[ "$(docker inspect --format "{{ index .Config.Labels \"$ownership_label\" }}" "$failed_id")" == "phoenix" ]]; then
      docker rm --force "$failed_id" >/dev/null
    fi
    echo "Phoenix could not bind to local port $PHOENIX_UI_PORT." >&2
    echo "Stop the process using that port or retry with PHOENIX_UI_PORT set to another port." >&2
    exit 1
  fi
fi

graphql_url="$PHOENIX_UI_URL/graphql"
otlp_url="$PHOENIX_UI_URL/v1/traces"
for _ in $(seq 1 60); do
  if curl --fail --silent --show-error \
    --header 'Content-Type: application/json' \
    --data-binary '{"query":"{ projects(first: 1) { edges { node { name } } } }"}' \
    "$graphql_url" >/dev/null 2>&1 \
      && curl --fail --silent --show-error \
        --header 'Content-Type: application/x-protobuf' \
        --data-binary '' \
        "$otlp_url" >/dev/null 2>&1; then
    printf 'Phoenix is ready: %s/projects\n' "$PHOENIX_UI_URL"
    exit 0
  fi
  sleep 1
done

echo "Phoenix did not become ready at $PHOENIX_UI_URL." >&2
exit 1
