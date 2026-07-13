# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/hermes-sandbox-base@sha256:f76a2ed0509570b1ce5380327c7ebe2e120e97f524e9271e145d2ea34c83ba5e

FROM ${BASE_IMAGE} AS nemo-relay-builder
ARG NEMO_RELAY_CLI_VERSION=0.3.0
RUN mkdir -p /out/bin \
    && ARCH="$(uname -m)" \
    && case "$ARCH" in \
         x86_64) TARGET=x86_64-unknown-linux-musl ;; \
         aarch64) TARGET=aarch64-unknown-linux-musl ;; \
         *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;; \
       esac \
    && URL="https://github.com/NVIDIA/NeMo-Relay/releases/download/${NEMO_RELAY_CLI_VERSION}/nemo-relay-cli-${TARGET}-${NEMO_RELAY_CLI_VERSION}" \
    && curl -L --proto '=https' --tlsv1.2 -sSf "$URL" -o /out/bin/nemo-relay \
    && chmod 755 /out/bin/nemo-relay

FROM ${BASE_IMAGE}
USER root

ARG HERMES_UPGRADE_VERSION=v2026.5.16
ARG HERMES_UPGRADE_TARBALL_SHA256=c0a554050a50ee9a62f3fa5cd288a167ba5640c42d647d100cdea084b7294143
ARG UV_INSTALL_VERSION=0.11.8
RUN set -eu \
    && apt-get update -qq \
    && apt-get install -y --no-install-recommends curl ca-certificates socat \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf "https://astral.sh/uv/${UV_INSTALL_VERSION}/install.sh" | env INSTALLER_NO_MODIFY_PATH=1 sh \
    && UV_BIN="" \
    && for candidate in /root/.local/bin/uv /root/.cargo/bin/uv; do [ ! -x "$candidate" ] || { UV_BIN="$candidate"; break; }; done \
    && install -m 755 "$UV_BIN" /usr/local/bin/uv \
    && curl -fsSL "https://github.com/NousResearch/hermes-agent/archive/refs/tags/${HERMES_UPGRADE_VERSION}.tar.gz" -o /tmp/hermes.tgz \
    && echo "${HERMES_UPGRADE_TARBALL_SHA256}  /tmp/hermes.tgz" | sha256sum -c - \
    && find /opt/hermes -mindepth 1 -maxdepth 1 -not -name '.venv' -exec rm -rf {} + \
    && tar -xzf /tmp/hermes.tgz -C /opt/hermes --strip-components=1 \
    && rm /tmp/hermes.tgz \
    && cd /opt/hermes \
    && UV_PROJECT_ENVIRONMENT=/opt/hermes/.venv uv sync \
       --extra messaging --extra web --extra cli --extra edge-tts --no-dev \
    && uv pip install --python /opt/hermes/.venv/bin/python \
       "aiohttp>=3.10,<4" "aiofiles>=23.2,<25" \
    && /opt/hermes/.venv/bin/python -c "import aiohttp, aiofiles" \
    && chown -R sandbox:sandbox /opt/hermes

COPY --from=nemo-relay-builder /out/bin/nemo-relay /usr/local/bin/nemo-relay
COPY agents/hermes/nemo-relay/finalize-hook /usr/local/bin/nemo-relay-finalize-hook
COPY agents/hermes/nemo-relay/hermes-cli-shim /usr/local/lib/nemoclaw/bin/hermes
COPY agents/hermes/plugins/nemo-relay/ /opt/nemo-relay-hermes-plugin/
COPY agents/hermes/generate-config.ts /opt/nemoclaw-generate-config.ts
COPY agents/hermes/start.sh /usr/local/bin/nemoclaw-start
RUN chmod 755 /usr/local/bin/nemo-relay /usr/local/bin/nemo-relay-finalize-hook \
      /usr/local/lib/nemoclaw/bin/hermes /usr/local/bin/nemoclaw-start \
    && chmod -R a+rX /opt/nemo-relay-hermes-plugin

ARG PHOENIX_COLLECTOR_ENDPOINT=""
ARG NEMO_RELAY_PROJECT_NAME="finguard-payment-ops"
COPY agents/hermes/nemo-relay/plugins.toml.in /tmp/plugins.toml.in
COPY agents/hermes/render-relay-config.py /tmp/render-relay-config.py
RUN PHOENIX_URL="${PHOENIX_COLLECTOR_ENDPOINT}" PROJECT="${NEMO_RELAY_PROJECT_NAME}" \
    python3 /tmp/render-relay-config.py \
    && rm /tmp/render-relay-config.py /tmp/plugins.toml.in

ARG NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b
ENV NEMOCLAW_MODEL=${NEMOCLAW_MODEL} \
    NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1 \
    NEMOCLAW_MESSAGING_CHANNELS_B64=W10= \
    HERMES_HOME=/sandbox/.hermes \
    HERMES_DISABLE_LAZY_INSTALLS=1 \
    PATH=/usr/local/lib/nemoclaw/bin:/opt/hermes/.venv/bin:${PATH}

USER sandbox
WORKDIR /sandbox
COPY --chown=sandbox:sandbox agents/hermes/SOUL.md /sandbox/.hermes/SOUL.md
COPY --chown=sandbox:sandbox skills/ /sandbox/.hermes/skills/
RUN node --experimental-strip-types /opt/nemoclaw-generate-config.ts \
    && mkdir -p /sandbox/.hermes/plugins/nemo-relay \
    && cp -r /opt/nemo-relay-hermes-plugin/* /sandbox/.hermes/plugins/nemo-relay/

EXPOSE 8642
ENTRYPOINT ["/usr/local/bin/nemoclaw-start"]
