# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
FROM python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ripgrep xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git \
      /opt/hermes-agent \
    && cd /opt/hermes-agent \
    && git checkout 345cd2b057a452236de401d3534b8502a7465e8d \
    && python -m pip install --no-cache-dir -e '.[mcp]'

RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /workspace \
    && chown agent:agent /workspace
USER agent
ENV HOME=/home/agent
WORKDIR /workspace

RUN command -v hermes \
    && hermes --version
