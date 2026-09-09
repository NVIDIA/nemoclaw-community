# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Sandbox image for one Hermes bot, with Hermes Agent pre-installed at a pinned
# release. Baking Hermes in means a sandbox never needs GitHub, PyPI, or npm at
# run time, so the egress policy can be reduced to the inference endpoint plus
# teammates, and spawning a bot takes seconds rather than minutes.
#
# Every package below was a hard failure during development, not a precaution.
FROM ubuntu:24.04
ARG HERMES_REF=v2026.8.31
ENV DEBIAN_FRONTEND=noninteractive

# python3.11: the installer otherwise asks uv to fetch a standalone CPython from
#             GitHub releases.
# xz-utils, libatomic1, build-essential: the Node.js step (extract, run, build
#             node-pty) needs all three or the installer exits before Hermes lands.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl gnupg \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        python3 python3-venv python3-pip \
        git jq iproute2 sudo xz-utils libatomic1 build-essential openssl \
 && rm -rf /var/lib/apt/lists/*

# OpenShell requires a user and group literally named "sandbox".
RUN groupadd -g 2000 sandbox \
 && useradd -u 2000 -g 2000 -m -s /bin/bash sandbox \
 && mkdir -p /sandbox && chown -R sandbox:sandbox /sandbox

# HOME must be /sandbox. Under Landlock, /home/sandbox is not writable even when
# it is owned by the sandbox user.
ENV HOME=/sandbox
ENV HERMES_HOME=/sandbox/.hermes
WORKDIR /sandbox

# Install Hermes as the sandbox user at the pinned ref. --skip-computer-use
# avoids the Chromium download; bots do not drive a browser here.
USER sandbox
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o /tmp/install.sh \
 && bash /tmp/install.sh --branch "${HERMES_REF}" --skip-computer-use --no-skills \
      > /sandbox/install.log 2>&1 \
 || { tail -40 /sandbox/install.log; exit 1; } \
 && /sandbox/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version \
 && rm -f /tmp/install.sh
USER root

# Record what was baked in, for `swarm doctor`.
RUN echo "${HERMES_REF}" > /etc/hermes-ref

# OpenShell 0.0.101+ refuses to start an image whose OCI USER is root
# ("OCI USER 'root' selects root", ContainerRestarting). Everything swarm does
# inside the sandbox writes under /sandbox, which this user owns.
USER sandbox

# The container must not exit: OpenShell injects its own entrypoint and a
# returning CMD yields "ContainerRestarting".
CMD ["sleep", "infinity"]
