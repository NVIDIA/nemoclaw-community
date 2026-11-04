# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
FROM ghcr.io/nvidia/nemoclaw/hermes-sandbox-base@sha256:c588bf76ba1c280f8a366bdfd672193e852de4f509a280662c7070a9b6e2fa48
USER root
WORKDIR /opt/decision-guard
COPY agent_runner.py mail_client.py scenario.py network_probes.py ./
COPY --chown=sandbox:sandbox hermes-config.yaml /sandbox/.hermes/config.yaml
ENV TERMINAL_ENV=local HERMES_HOME=/sandbox/.hermes HOME=/sandbox
ENV HERMES_DISABLE_LAZY_INSTALLS=1 HERMES_LAZY_INSTALL_TARGET=""
RUN chown sandbox:sandbox /sandbox && chmod 0700 /sandbox
USER sandbox
WORKDIR /sandbox
ENTRYPOINT ["/bin/sh", "-c", "sleep infinity"]
