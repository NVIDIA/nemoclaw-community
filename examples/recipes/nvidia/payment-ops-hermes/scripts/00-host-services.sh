#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

require_command docker
mkdir -p "$STATE_DIR"
docker compose -f "$EXAMPLE_DIR/observability/phoenix-compose.yml" up -d

echo "Waiting for Phoenix on port 6006..."
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:6006 >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://127.0.0.1:6006 >/dev/null || {
  docker compose -f "$EXAMPLE_DIR/observability/phoenix-compose.yml" logs --tail=50 >&2
  echo "Phoenix did not become healthy" >&2
  exit 1
}
echo "Phoenix ready: http://127.0.0.1:6006"
