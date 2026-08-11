#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# stage-skills.sh — stage this example's skills into the sandbox agent's
# skill library (operator skill Phase 2b). Transactional per skill: copy into
# a hidden temp dir, chown ONLY what was staged, swap in a single exec — a
# failed copy leaves the existing skill untouched. The host-side operator
# skill is deliberately excluded.
set -euo pipefail

SANDBOX="${SANDBOX:-hermes-direct}"
EXAMPLE="${EXAMPLE:-$(cd "$(dirname "$0")/../../.." && pwd)}"
SKX=/sandbox/.hermes-data/skills

. "$(dirname "$0")/lib.sh"
C=$(resolve_sandbox_container "$SANDBOX") || { echo "FATAL: container selection failed"; exit 1; }

for d in "$EXAMPLE"/skills/*/; do
  name=$(basename "$d")
  [ "$name" = "setup-workshop-nemoclaw-operator" ] && continue
  docker exec "$C" rm -rf "$SKX/.stage-$name"
  docker cp "$d" "$C:$SKX/.stage-$name"
  docker exec "$C" chown -R sandbox:sandbox "$SKX/.stage-$name"
  docker exec "$C" sh -c "rm -rf '$SKX/$name' && mv '$SKX/.stage-$name' '$SKX/$name'"
  echo "staged: $name"
done
docker exec "$C" ls "$SKX"
