# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermes sandbox image — Hermes Agent + NemoClaw plugin inside OpenShell
#
# Layers PR-specific code (plugin, config, startup script) on top of the
# pre-built Hermes base image. Mirrors the OpenClaw Dockerfile structure.

# ARGs that appear in FROM instructions must be declared before the first FROM
# so Docker treats them as global build args (multi-stage scoping rule).
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/hermes-sandbox-base:latest

# ── Stage 0: build the MS Graph API sidecar binary ────────────────────────────
# PyInstaller produces a self-contained executable at a unique path
# (/usr/local/bin/ms-graph-sidecar), distinct from /usr/bin/python3,
# enabling OpenShell binary-path policy enforcement to restrict token-manager
# access to the sidecar only.
#
# IMPORTANT: build inside ${BASE_IMAGE}, not python:3.12-slim, so the compiled
# binary links against the same glibc as the runtime. Using a newer builder
# image (e.g. Debian trixie glibc 2.41) produces a binary that crashes on the
# Ubuntu 22.04 runtime (glibc 2.35) with "GLIBC_2.38 not found".
FROM ${BASE_IMAGE} AS sidecar-builder
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends binutils python3-pip libpython3.11 \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir --break-system-packages aiohttp pyinstaller
COPY agents/hermes/sidecars/ms_graph_sidecar/ms_graph_sidecar.py /build/
WORKDIR /build
RUN pyinstaller \
      --onefile \
      --name ms-graph-sidecar \
      --hidden-import aiohttp \
      --hidden-import aiohttp.web \
      ms_graph_sidecar.py

# ── Main sandbox image ────────────────────────────────────────────────────────
FROM ${BASE_IMAGE}

# NeMo-Flow Phoenix OTLP endpoint — baked at image build time so start.sh
# reads it directly from the container ENV without relying on runtime injection.
# Empty string means no telemetry (standard behavior).
ARG PHOENIX_COLLECTOR_ENDPOINT=""
ENV PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT}

# Host address of the Outlook token manager (port 8765).
# Baked at image build time using the same pattern as PHOENIX_COLLECTOR_ENDPOINT —
# start.sh reads it as a real env var so the sidecar can open a TCP connection
# without going through the OpenShell provider placeholder mechanism.
# Default works on Docker Desktop (Mac/Windows) and Linux with --add-host.
ARG TOKEN_MANAGER_HOST=host.docker.internal
ENV TOKEN_MANAGER_HOST=${TOKEN_MANAGER_HOST}

# Install the MS Graph sidecar binary from the builder stage.
# The distinct binary path enables OpenShell binary-path policy enforcement.
COPY --from=sidecar-builder /build/dist/ms-graph-sidecar /usr/local/bin/ms-graph-sidecar
RUN chmod 755 /usr/local/bin/ms-graph-sidecar

# Harden: remove unnecessary build tools and network probes
RUN (apt-get remove --purge -y gcc gcc-12 g++ g++-12 cpp cpp-12 make \
        netcat-openbsd netcat-traditional ncat 2>/dev/null || true) \
    && apt-get autoremove --purge -y \
    && rm -rf /var/lib/apt/lists/*

# Add dedicated user for the MS Graph sidecar (uid 1001).
# Running as a separate user from the sandbox (uid 1000) prevents the Hermes
# agent from accessing the sidecar's process memory via /proc.
RUN adduser --disabled-password --gecos "" --uid 1001 ms-graph-proxy

# Optional: register additional trusted CA certificates inside the sandbox.
# Drop *.crt files into the example-root certs/ directory before building —
# typically needed only when the build/runtime network performs TLS
# interception. Empty by default; update-ca-certificates is a safe no-op
# when no .crt files are present. See certs/README.md for details.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Install GitHub CLI (gh) — not in the base image.
# GH_TOKEN is set below so gh authenticates via the OpenShell provider pipeline.
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# ── Optional: NeMo-Flow patched Hermes + Phoenix observability ──────────
# When ENABLE_NEMO_FLOW=1, replace the unpatched Hermes from the base image
# with a NeMo-Flow-patched build. nemo-flow itself comes from PyPI (no Rust
# toolchain, no submodule, no separate base-image build needed). The patch
# itself patches Hermes — adding a [nemo-flow] extra, a hermes_agent.plugins
# entry point, and an ACG override seam in run_agent.py — so it's still
# required even with the PyPI install of nemo_flow itself.
#
# The patch is fetched from NeMo-Flow's GitHub tag at build time rather than
# vendored, so we never drift from upstream. Pin NEMO_FLOW_VERSION to the
# same release we install via pip; HERMES_NEMO_FLOW_COMMIT must match the
# Hermes commit that NeMo-Flow's patch was generated against (see
# https://github.com/NVIDIA/NeMo-Flow/blob/v0.1.0/third_party/sources.lock).
# sitecustomize-nemo-flow.py is example-owned (not in NeMo-Flow upstream)
# so it stays vendored.
ARG ENABLE_NEMO_FLOW=0
ARG NEMO_FLOW_VERSION=0.1.0
ARG HERMES_NEMO_FLOW_COMMIT=2367c6ffd53b16daa0ffa1b338f3f9ee5587d4d5

COPY agents/hermes/patches/sitecustomize-nemo-flow.py /tmp/sitecustomize-nemo-flow.py

# hadolint ignore=DL3013
RUN if [ "$ENABLE_NEMO_FLOW" = "1" ]; then \
        echo "[nemo-flow] Installing nemo-flow==${NEMO_FLOW_VERSION} from PyPI and patching Hermes" \
        && curl -fsSL "https://raw.githubusercontent.com/NVIDIA/NeMo-Flow/${NEMO_FLOW_VERSION}/patches/hermes-agent/0001-add-nemo-flow-integration.patch" \
             -o /tmp/nemo-flow.patch \
        && curl -fsSL "https://github.com/NousResearch/hermes-agent/archive/${HERMES_NEMO_FLOW_COMMIT}.tar.gz" \
             | tar -xz -C /tmp/ \
        && mv "/tmp/hermes-agent-${HERMES_NEMO_FLOW_COMMIT}" /tmp/hermes-agent \
        && git -C /tmp/hermes-agent init -q \
        && git -C /tmp/hermes-agent apply /tmp/nemo-flow.patch \
        && pip3 install --no-cache-dir --break-system-packages --force-reinstall \
             "nemo-flow==${NEMO_FLOW_VERSION}" \
             "/tmp/hermes-agent[nemo-flow,slack]" \
             "pyyaml==6.0.3" \
             "python-telegram-bot>=21.0" \
             "httpx>=0.27" \
             "slack-bolt>=1.19" \
        && hermes --version \
        && cp /tmp/sitecustomize-nemo-flow.py /usr/lib/python3.11/sitecustomize.py \
        && chmod 644 /usr/lib/python3.11/sitecustomize.py \
        && rm -rf /tmp/hermes-agent /tmp/nemo-flow.patch; \
    fi \
    && rm -f /tmp/sitecustomize-nemo-flow.py

# Hermes v2026.4.13+ auto-detects HTTPS_PROXY and skips fallback-IP
# transport when a proxy is present. The sandbox proxy chain
# (decode-proxy → OpenShell L7 proxy) handles credential placeholder
# rewriting and hostname-based policy enforcement. No monkey patch needed.
ENV HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=1 \
    GH_TOKEN=openshell:resolve:env:GITHUB_TOKEN

# Copy NemoClaw plugin for Hermes (Python-based)
COPY agents/hermes/plugin/ /opt/nemoclaw-hermes-plugin/

# Copy bridges and default cron jobs.
# Install under /usr/local/lib/ so Landlock's read_only /usr rule permits access.
COPY agents/hermes/bridges/ /usr/local/lib/nemoclaw-bridges/

# Copy config generation script and URL-decode proxy
COPY agents/hermes/generate-config.ts /opt/nemoclaw-generate-config.ts
COPY agents/hermes/patch-hermes-gateway.py /opt/nemoclaw-patch-hermes-gateway.py
COPY agents/hermes/decode-proxy.py /usr/local/bin/nemoclaw-decode-proxy
RUN chmod 755 /usr/local/bin/nemoclaw-decode-proxy
RUN python3 /opt/nemoclaw-patch-hermes-gateway.py

# NOTE: This example removes the upstream NemoClaw `COPY nemoclaw-blueprint/`
# step. Nothing in the Hermes runtime (start.sh, plugin/, bridges/, sidecars/,
# skills/) reads /sandbox/.nemoclaw/blueprints/0.1.0/ — it was build-time
# scaffolding only. Dropping it means the example doesn't need NemoClaw's
# nemoclaw-blueprint/ directory in its build context.

# Ensure sandbox user can read all /opt/nemoclaw-* and bridge files.
# Source files may have restrictive permissions that Docker COPY preserves.
RUN chmod -R a+rX /opt/nemoclaw-hermes-plugin/ \
    && chmod a+r /opt/nemoclaw-generate-config.ts \
    && chmod a+r /opt/nemoclaw-patch-hermes-gateway.py \
    && chmod -R a+rX /usr/local/lib/nemoclaw-bridges/

# Install shared sandbox-init.sh primitives (capability drop, atomic rc-file
# rewrite, cleanup_on_signal, verify_config_integrity, validate/harden symlinks,
# emit_sandbox_sourced_file, validate_tmp_permissions, lock_rc_files).
# start.sh sources this from /usr/local/lib/nemoclaw/sandbox-init.sh.
COPY scripts/lib/sandbox-init.sh /usr/local/lib/nemoclaw/sandbox-init.sh
RUN chmod 644 /usr/local/lib/nemoclaw/sandbox-init.sh

# Copy startup script
COPY agents/hermes/start.sh /usr/local/bin/nemoclaw-start
RUN chmod 755 /usr/local/bin/nemoclaw-start

# Copy bundled agent memories and skills into the writable state directories.
# These are baked at build time so the agent knows its capabilities on first run
# without requiring a network fetch. The sandbox user owns these files.
COPY --chown=sandbox:sandbox agents/hermes/SOUL.md /sandbox/.hermes-data/SOUL.md
COPY --chown=sandbox:sandbox agents/hermes/skills/ /sandbox/.hermes-data/skills/

# Build args for config that varies per deployment.
ARG NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b
ARG NEMOCLAW_PROVIDER_KEY=custom
ARG NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1
ARG CHAT_UI_URL=http://127.0.0.1:8642
ARG NEMOCLAW_MESSAGING_CHANNELS_B64=W10=
ARG NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=e30=
ARG OUTLOOK_TARGET_MAILBOX=
ARG OUTLOOK_REPLY_TO=
ARG OUTLOOK_ALLOWED_SENDERS=
ARG SOURCE_ETL_GITHUB_REPO=
ARG SOURCE_ETL_FORUM_TAG=
ARG SOURCE_ETL_API_URL=
ARG SOURCE_ETL_API_HOST=
ARG SOURCE_ETL_API_PORT=3100
ARG NEMOCLAW_BUILD_ID=default
ARG MS_GRAPH_SERVICES="outlook"

# Promote build-args to env vars for the config generation script.
ENV NEMOCLAW_MODEL=${NEMOCLAW_MODEL} \
    NEMOCLAW_PROVIDER_KEY=${NEMOCLAW_PROVIDER_KEY} \
    NEMOCLAW_INFERENCE_BASE_URL=${NEMOCLAW_INFERENCE_BASE_URL} \
    CHAT_UI_URL=${CHAT_UI_URL} \
    NEMOCLAW_MESSAGING_CHANNELS_B64=${NEMOCLAW_MESSAGING_CHANNELS_B64} \
    NEMOCLAW_MESSAGING_ALLOWED_IDS_B64=${NEMOCLAW_MESSAGING_ALLOWED_IDS_B64} \
    OUTLOOK_TARGET_MAILBOX=${OUTLOOK_TARGET_MAILBOX} \
    OUTLOOK_REPLY_TO=${OUTLOOK_REPLY_TO} \
    OUTLOOK_ALLOWED_SENDERS=${OUTLOOK_ALLOWED_SENDERS} \
    MS_GRAPH_SERVICES=${MS_GRAPH_SERVICES} \
    SOURCE_ETL_GITHUB_REPO=${SOURCE_ETL_GITHUB_REPO} \
    SOURCE_ETL_FORUM_TAG=${SOURCE_ETL_FORUM_TAG} \
    SOURCE_ETL_API_URL=${SOURCE_ETL_API_URL} \
    SOURCE_ETL_API_HOST=${SOURCE_ETL_API_HOST} \
    SOURCE_ETL_API_PORT=${SOURCE_ETL_API_PORT}

WORKDIR /sandbox
USER sandbox

# Generate Hermes config.yaml and .env from build args.
# config.yaml is immutable at runtime (Landlock read-only on /sandbox/.hermes).
# .env holds API key placeholders for OpenShell provider pipeline.
# SECURITY: Uses a separate script file instead of inline code to avoid
# code injection via build-arg interpolation (same concern as OpenClaw C-2).
RUN node --experimental-strip-types /opt/nemoclaw-generate-config.ts

# Install NemoClaw plugin into Hermes
RUN mkdir -p /sandbox/.hermes-data/plugins/nemoclaw \
    && cp -r /opt/nemoclaw-hermes-plugin/* /sandbox/.hermes-data/plugins/nemoclaw/

# Symlink SOUL.md into the immutable home so Hermes's ensure_hermes_home() finds it.
RUN ln -s /sandbox/.hermes-data/SOUL.md /sandbox/.hermes/SOUL.md

# Lock .hermes via DAC: chown to root so sandbox user cannot modify config.
# Same pattern as OpenClaw — Landlock provides defense-in-depth.
# hadolint ignore=DL3002
USER root
RUN chown root:root /sandbox/.hermes \
    && rm -rf /root/.cache/pip /sandbox/.cache \
    && find /sandbox/.hermes -mindepth 1 -maxdepth 1 -exec chown -h root:root {} + \
    && chmod 755 /sandbox/.hermes \
    && chmod 444 /sandbox/.hermes/config.yaml \
    && chmod 444 /sandbox/.hermes/.env

# Pin config hash at build time for integrity verification at startup.
RUN sha256sum /sandbox/.hermes/config.yaml /sandbox/.hermes/.env \
    > /sandbox/.hermes/.config-hash \
    && chmod 444 /sandbox/.hermes/.config-hash \
    && chown root:root /sandbox/.hermes/.config-hash

# start.sh handles privilege separation: runs as root initially to perform
# symlink validation and hardening, then drops to 'gateway' user via gosu
# for the agent process. See the root-path branch in start.sh.
ENTRYPOINT ["/usr/local/bin/nemoclaw-start"]
CMD ["/bin/bash"]
