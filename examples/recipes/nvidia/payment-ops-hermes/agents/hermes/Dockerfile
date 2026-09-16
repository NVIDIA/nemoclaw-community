# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Published from NVIDIA/NemoClaw main with Hermes 0.20.6 and its native
# NeMo Relay 0.7.2 integration already installed.
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/hermes-sandbox-base@sha256:c588bf76ba1c280f8a366bdfd672193e852de4f509a280662c7070a9b6e2fa48

FROM ${BASE_IMAGE}
ARG HERMES_SEMVER=0.20.6
ARG NEMO_RELAY_VERSION=0.7.2

USER root

RUN test "$(/opt/hermes/.venv/bin/python -c 'from importlib.metadata import version; print(version("hermes-agent"))')" = "$HERMES_SEMVER" \
    && test "$(/opt/hermes/.venv/bin/python -c 'from importlib.metadata import version; print(version("nemo-relay"))')" = "$NEMO_RELAY_VERSION" \
    && hermes --version

# Hermes loads this immutable Relay v3 configuration in-process. ATIF remains
# local to /sandbox/atif while OpenInference spans flow to the host Phoenix.
COPY agents/hermes/nemo-relay/plugins.toml /etc/nemo-relay/config/plugins.toml
RUN mkdir -p /etc/nemo-relay/config /etc/nemo-relay/xdg /etc/nemo-relay/runtime \
    && chown -R root:root /etc/nemo-relay \
    && chmod 555 /etc/nemo-relay /etc/nemo-relay/config \
       /etc/nemo-relay/xdg /etc/nemo-relay/runtime \
    && chmod 444 /etc/nemo-relay/config/plugins.toml \
    && /opt/hermes/.venv/bin/python -c 'import tomllib; from pathlib import Path; from nemo_relay import plugin; path = Path("/etc/nemo-relay/config/plugins.toml"); config = tomllib.loads(path.read_text(encoding="utf-8")); diagnostics = plugin.validate(config).get("diagnostics", []); assert not diagnostics, diagnostics'

COPY agents/hermes/generate-config.ts /opt/nemoclaw-generate-config.ts
COPY agents/hermes/start.sh /usr/local/bin/nemoclaw-start
RUN chmod 755 /usr/local/bin/nemoclaw-start

ARG NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b
ENV NEMOCLAW_MODEL=${NEMOCLAW_MODEL} \
    NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1 \
    HERMES_HOME=/sandbox/.hermes \
    HERMES_DISABLE_LAZY_INSTALLS=1 \
    HERMES_NEMO_RELAY_PLUGINS_TOML=/etc/nemo-relay/config/plugins.toml \
    XDG_CONFIG_HOME=/etc/nemo-relay/xdg

USER sandbox
WORKDIR /sandbox
COPY --chown=sandbox:sandbox agents/hermes/SOUL.md /sandbox/.hermes/SOUL.md
COPY --chown=sandbox:sandbox skills/ /sandbox/.hermes/skills/
RUN node --experimental-strip-types /opt/nemoclaw-generate-config.ts

EXPOSE 8642
ENTRYPOINT ["/usr/local/bin/nemoclaw-start"]
