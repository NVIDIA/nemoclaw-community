#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:v0.22.0}"
CONTAINER_NAME="${VLLM_CONTAINER_NAME:-nemotron-ultra-vllm}"
MODEL="${VLLM_MODEL:-nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4}"
SERVED_NAME="${VLLM_SERVED_NAME:-nemotron-ultra}"
PORT="${VLLM_PORT:-8000}"
GPU_DEVICE="${VLLM_GPU_DEVICE:-all}"
HF_CACHE_DIR="${HF_HOME:-$HOME/.cache/huggingface}"

mkdir -p "$HF_CACHE_DIR"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

GPU_ARG="all"
if [[ "$GPU_DEVICE" != "all" ]]; then
  GPU_ARG="device=${GPU_DEVICE}"
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  --gpus "$GPU_ARG" \
  --ipc=host \
  --network=host \
  --shm-size=16g \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v "$HF_CACHE_DIR:/root/.cache/huggingface" \
  -e VLLM_WEIGHT_OFFLOADING_DISABLE_PIN_MEMORY=1 \
  -e VLLM_NVFP4_GEMM_BACKEND=flashinfer-trtllm \
  -e "HF_TOKEN=${HF_TOKEN:-}" \
  -e "HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}" \
  "$IMAGE" \
  "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --reasoning-parser nemotron_v3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --cpu-offload-gb 150 \
  --cpu-offload-params experts \
  --kernel_config '{"enable_flashinfer_autotune": false}' \
  --max-num-seqs 256 \
  --gpu-memory-utilization 0.9

echo "$CONTAINER_NAME"
