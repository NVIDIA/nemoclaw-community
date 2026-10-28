#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# loop/eval.sh AGENT_DIR OUT SPLIT [ATTEMPTS]: one agent on one split of evals/ (train, val or
# test), ATTEMPTS runs per task (default 2), then each run's grade onto its trace and a summary.
# MODEL defaults to Nemotron 3.5 Super VL on the Helix gateway;
# CAD_SLOTS trials run at once (default 4: 3 GiB each).
set -uo pipefail   # a failed step, or summary.py behind tee, fails the script
AGENT=$(cd "$1" && pwd) || exit 1; SPLIT=$3; N=${4:-2}
mkdir -p "$2" && OUT=$(cd "$2" && pwd) || exit 1
cd "$(dirname "$0")/.."   # the example root: harness/, evals/, publish.py, .env
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -n "${DOCKER_HOST:-}" ] || [ ! -S "$HOME/.colima/default/docker.sock" ] || export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
[ ! -e "$OUT/$SPLIT" ] || { echo "$OUT/$SPLIT exists"; exit 1; }
docker build -q -t cad-verifier evals/verifier > /dev/null || exit 1   # every task's verifier starts from it
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/$SPLIT.started"
PYTHONPATH=harness harbor run -y -p "evals/$SPLIT" -a cad_agent:CadAgent --ak agent_dir="$AGENT" \
  -m "${MODEL:-nvidia-nvidia-nemotron-3-5-super-vl}" -k "$N" -n "${CAD_SLOTS:-4}" \
  --max-retries 2 --retry-include GatewayLost --jobs-dir "$OUT" --job-name "$SPLIT" > "$OUT/$SPLIT.out" 2>&1 || { echo "harbor failed: see $OUT/$SPLIT.out"; exit 1; }
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/$SPLIT.ended"
python3 publish.py scores "$OUT/$SPLIT" > "$OUT/$SPLIT.scores" 2>&1 || { echo "publish failed: see $OUT/$SPLIT.scores"; exit 1; }
python3 loop/summary.py "$OUT/$SPLIT" | tee "$OUT/$SPLIT.summary"
