# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Virtual env lives outside /app so a source volume mount doesn't shadow it
ENV VIRTUAL_ENV=/venv
ENV PATH="/venv/bin:$PATH"

# Install deps before copying source (Docker cache layer)
COPY pyproject.toml .
RUN uv venv /venv \
    && uv pip install --python /venv/bin/python msal aiohttp cryptography

# Copy source
COPY token_manager/ token_manager/

# Non-root user
RUN adduser --disabled-password --gecos "" --uid 1000 nemoclaw \
    && chown -R nemoclaw:nemoclaw /app /venv \
    && mkdir -p /token-cache \
    && chown nemoclaw:nemoclaw /token-cache
USER nemoclaw

CMD ["python", "-m", "token_manager.main"]
