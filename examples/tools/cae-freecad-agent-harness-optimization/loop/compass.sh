#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# loop/compass.sh ROUND_DIR: NeMo Compass on the train runs in ROUND_DIR/runs (loop/eval.sh,
# their time window in Intake), with ROUND_DIR/agent as the code base, then the Insights to
# Studio (README Step 2). Writes ROUND_DIR/analyst.yaml and ROUND_DIR/insights.yml.
set -eu
D=$(cd "$1" && pwd); S=$(cat "$D/runs/train.started"); E=$(cat "$D/runs/train.ended")
cd "$(dirname "$0")/.."   # the example root: analyst.yaml, publish.py, .env
[ -f .env ] && { set -a; . ./.env; set +a; }
NAME=$(sed -n 's/^name: *//p' "$D/agent/agent.yaml")   # the agent name its traces carry
sed -e "s#base_url: .*#base_url: ${NHX_BASE_URL:-http://localhost:8080}#" -e "s#^code_base: .*#code_base: $D/agent#" \
    -e "s#agent_name: .*#agent_name: $NAME#" -e "s#started_at_gte: .*#started_at_gte: '$S'#" \
    -e "s#started_at_lte: .*#started_at_lte: '$E'#" analyst.yaml > "$D/analyst.yaml"
compass --config "$D/analyst.yaml" --output-path "$D/insights.yml" > "$D/compass.out" 2>&1
uv run -q --with pyyaml python publish.py insights "$D/insights.yml" --agent "$NAME" > "$D/insights.out" 2>&1
