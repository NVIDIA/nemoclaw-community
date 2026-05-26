# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermes sandbox image — Hermes Agent + NemoClaw plugin inside OpenShell
#
# Layers PR-specific code (plugin, config, startup script) on top of the
# pre-built Hermes base image. Mirrors the OpenClaw Dockerfile structure.

# ARGs that appear in FROM instructions must be declared before the first FROM
# so Docker treats them as global build args (multi-stage scoping rule).
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/hermes-sandbox-base@sha256:f76a2ed0509570b1ce5380327c7ebe2e120e97f524e9271e145d2ea34c83ba5e

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
    && export PY_MINOR="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" \
    && apt-get install -y --no-install-recommends "libpython${PY_MINOR}" binutils python3-pip \
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

# ── Stage 1: build the nemo-relay CLI binary ──────────────────────────────────
# Built inside ${BASE_IMAGE} so the resulting binary links against the same
# glibc as the runtime — same constraint as the sidecar-builder stage above.
# 0.3.0-beta.2 is the first NeMo-Relay release on crates.io (the predecessor
# crate `nemo-flow-cli` was published through 0.2.0 before the project's rename
# from NeMo-Flow). `cargo install` is the simplest reproducible path; the
# ~3-5 min toolchain bootstrap is amortized across the cargo target cache when
# the version pin doesn't change.
FROM ${BASE_IMAGE} AS nemo-relay-builder
ARG NEMO_RELAY_CLI_VERSION=0.3.0-beta.2
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
       | sh -s -- -y --default-toolchain stable --profile minimal \
    && /root/.cargo/bin/cargo install --locked --root /out \
       nemo-relay-cli --version "${NEMO_RELAY_CLI_VERSION}"
# Produces /out/bin/nemo-relay

# ── Main sandbox image ────────────────────────────────────────────────────────
FROM ${BASE_IMAGE}

# NeMo-Relay Phoenix OTLP endpoint — baked at image build time so start.sh
# reads it directly from the container ENV without relying on runtime injection.
# Empty string means no telemetry (standard behavior).
ARG PHOENIX_COLLECTOR_ENDPOINT=""
ENV PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT}

# Host address of the Outlook token manager (port 8765).
# Baked at image build time using the same pattern as PHOENIX_COLLECTOR_ENDPOINT —
# start.sh reads it as a real env var so the sidecar can open a TCP connection
# without going through the OpenShell provider placeholder mechanism.
# Default works with the package-managed and snap-managed OpenShell gateway
# services, which expose host-routed services at host.openshell.internal.
ARG TOKEN_MANAGER_HOST=host.openshell.internal
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

RUN pip3 install --no-cache-dir --break-system-packages "httpx>=0.27" "markdown-it-py>=3"

# ── Upgrade Hermes from base image's v0.11.0 to v0.14.0 ─────────────────
# NemoClaw's base image (even at its latest tag) pins HERMES_VERSION=v2026.4.23
# (Hermes v0.11.0). v0.11.0's plugin hooks ship metadata-only kwargs to
# pre_api_request / post_api_request — no real messages, no real response —
# so observability backends (Langfuse, NeMo-Relay's hermes adapter) cannot
# emit LLM spans with full content. v0.14.0 (v2026.5.16, "The Foundation
# Release") adds rich-kwargs hook delivery and ships the bundled Langfuse
# plugin that depends on it.
#
# We mirror NemoClaw's tarball + uv-sync install pattern, but for a newer
# version. /opt/hermes/.venv is preserved across the upgrade so uv can
# incrementally reconcile dependencies against v0.14.0's uv.lock.
ARG HERMES_UPGRADE_VERSION=v2026.5.16
ARG HERMES_UPGRADE_TARBALL_SHA256=c0a554050a50ee9a62f3fa5cd288a167ba5640c42d647d100cdea084b7294143
# messaging: slack-bolt + slack-sdk + aiohttp (and friends) for the Slack
#   platform path.
# web: fastapi + uvicorn for Hermes's web tools.
# cli: simple-term-menu, used by `hermes chat` TUI menus. Without this the
#   TUI banner path can try to lazy-install at runtime, which the
#   locked-down sandbox can't satisfy.
# edge-tts: edge-tts==7.2.7. The TTS check_fn fires during banner
#   enumeration regardless of toolset config; pre-installing avoids the
#   PyPI fetch attempt at runtime. HERMES_DISABLE_LAZY_INSTALLS=1 (set
#   below + in start.sh) is the belt-and-suspenders fallback for any
#   other lazy feature we haven't pre-installed.
ARG HERMES_UV_EXTRAS="messaging web cli edge-tts"
# Match the uv version NemoClaw uses for the base-image install.
ARG UV_INSTALL_VERSION=0.11.8

USER root
RUN set -eu \
    && curl -LsSf "https://astral.sh/uv/${UV_INSTALL_VERSION}/install.sh" \
       | env INSTALLER_NO_MODIFY_PATH=1 sh \
    && UV_BIN="" \
    && for candidate in /root/.local/bin/uv /root/.cargo/bin/uv /usr/local/bin/uv; do \
         if [ -x "$candidate" ]; then UV_BIN="$candidate"; break; fi; \
       done \
    && if [ -z "$UV_BIN" ]; then echo "uv installer did not produce a binary in any known location" >&2; exit 1; fi \
    && install -m 755 "$UV_BIN" /usr/local/bin/uv \
    && /usr/local/bin/uv --version \
    && curl -fsSL "https://github.com/NousResearch/hermes-agent/archive/refs/tags/${HERMES_UPGRADE_VERSION}.tar.gz" \
       -o /tmp/hermes.tgz \
    && echo "${HERMES_UPGRADE_TARBALL_SHA256}  /tmp/hermes.tgz" | sha256sum -c - \
    && find /opt/hermes -mindepth 1 -maxdepth 1 -not -name '.venv' -exec rm -rf {} + \
    && tar -xzf /tmp/hermes.tgz -C /opt/hermes --strip-components=1 \
    && rm /tmp/hermes.tgz \
    && cd /opt/hermes \
    && extras_args="" \
    && for e in ${HERMES_UV_EXTRAS}; do extras_args="${extras_args} --extra ${e}"; done \
    && UV_PROJECT_ENVIRONMENT=/opt/hermes/.venv /usr/local/bin/uv sync \
       ${extras_args} --no-dev \
    && chown -R sandbox:sandbox /opt/hermes

# ── NeMo-Relay 0.3.0 sidecar gateway integration ─────────────────────────
# Hermes stays unpatched (from BASE_IMAGE). start.sh launches a long-running
# nemo-relay daemon; Hermes processes POST hook events to it via
# NEMO_RELAY_GATEWAY_URL. ATIF writes are local-disk-only (no collector
# required); set PHOENIX_COLLECTOR_ENDPOINT to additionally export
# OpenInference traces to Phoenix.
#
# agents/hermes/patches/ is example-owned (not in NeMo-Relay upstream). It
# holds the PYTHONPATH-targeted sitecustomize.py bootstrap (Slack-SDK
# placeholder rewrite) and the nemoclaw_patches.py chain-loaded bundle
# (Slack catch-all slash command).
COPY --from=nemo-relay-builder /out/bin/nemo-relay /usr/local/bin/nemo-relay
RUN chmod 755 /usr/local/bin/nemo-relay

RUN mkdir -p /usr/local/lib/nemoclaw/bin

# Per-turn finalize hook. Hermes only fires `on_session_finalize` from its
# idle-session expiry watcher (~5 min default), but NeMo-Relay's ATIF writer
# and root-span closer only act on `on_session_finalize` / `on_session_reset`.
# This hook handler, registered as a second command on `on_session_end`,
# rewrites the event name and re-posts to the gateway so each turn closes
# its agent scope.
COPY agents/hermes/nemo-relay/finalize-hook /usr/local/lib/nemoclaw/bin/nemo-relay-finalize-hook
RUN chmod 755 /usr/local/lib/nemoclaw/bin/nemo-relay-finalize-hook

# Interactive-shell shim for `hermes`. Prepended to PATH for sandbox shells
# (via _PROXY_ENV_FILE in start.sh) so `hermes` resolves here first; blocks
# setup/doctor in-sandbox and execs the upstream binary for everything else.
COPY agents/hermes/nemo-relay/hermes-cli-shim /usr/local/lib/nemoclaw/bin/hermes
RUN chmod 755 /usr/local/lib/nemoclaw/bin/hermes

COPY agents/hermes/patches/ /usr/local/lib/nemoclaw-patches/

# Pin slack-bolt / python-telegram-bot / pyyaml / httpx into Hermes's venv
# interpreter so the sitecustomize patches (Slack catch-all, SDK placeholder
# rewrite) find the modules they wrap. hadolint ignore=DL3013
RUN pip3 install --no-cache-dir --break-system-packages \
       "pyyaml==6.0.3" \
       "python-telegram-bot>=21.0" \
       "httpx>=0.27" \
       "slack-bolt>=1.19" \
    && hermes --version \
    && export PY_SITE_DIR="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && ln -sfn /usr/local/lib/nemoclaw-patches/sitecustomize.py "${PY_SITE_DIR}/sitecustomize.py"

# ── NeMo-Relay plugin config (immutable, baked at build time) ────────────
# Discovery order: /etc/nemo-relay → project ./.nemo-relay → user XDG
# (see NeMo-Relay crates/cli/src/config.rs). /etc/ is the cleanest location
# for a containerized agent because it ignores CWD.
#
# Only plugins.toml is baked — observability component (ATIF + OpenInference).
# The daemon doesn't need a config.toml here: --bind is passed explicitly by
# start.sh, and the wrapped-CLI `[agents.hermes]` block isn't used in the
# sidecar/daemon architecture (agents POST to the daemon; it doesn't launch
# them).
COPY agents/hermes/nemo-relay/plugins.toml.in /tmp/nemo-relay-plugins.toml.in
RUN mkdir -p /etc/nemo-relay \
    && PHOENIX_URL="${PHOENIX_COLLECTOR_ENDPOINT:-}" \
    && if [ -z "$PHOENIX_URL" ]; then \
         PHOENIX_ENABLED=false; PHOENIX_ENDPOINT=""; \
       else \
         # PHOENIX_COLLECTOR_ENDPOINT is consumed verbatim — the user supplies
         # the full OTLP HTTP/binary URL (typically including the /v1/traces
         # suffix). The trailing-slash strip is the only normalization. See
         # .env.example and README for the documented value format.
         PHOENIX_ENABLED=true; PHOENIX_ENDPOINT="${PHOENIX_URL%/}"; \
       fi \
    && sed -e "s|@@PHOENIX_ENABLED@@|${PHOENIX_ENABLED}|g" \
           -e "s|@@PHOENIX_ENDPOINT@@|${PHOENIX_ENDPOINT}|g" \
       /tmp/nemo-relay-plugins.toml.in > /etc/nemo-relay/plugins.toml \
    && rm /tmp/nemo-relay-plugins.toml.in \
    && chmod 444 /etc/nemo-relay/plugins.toml

# Hermes v2026.4.13+ auto-detects HTTPS_PROXY and skips fallback-IP
# transport when a proxy is present. The sandbox proxy chain
# (decode-proxy → OpenShell L7 proxy) handles credential placeholder
# rewriting and hostname-based policy enforcement. The Python preload
# rewrites Slack SDK-shaped placeholders before HTTPS serialization.
#
# Only HERMES_HOME and HERMES_DISABLE_LAZY_INSTALLS reliably reach
# user processes — OpenShell's exec-session allowlist strips most other
# HERMES_* vars. PID-1 (start.sh-launched gateway) keeps everything;
# HERMES_DISABLE_LAZY_INSTALLS is also re-exported from start.sh's
# _PROXY_ENV_FILE so interactive shells get it.
ENV HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=1 \
    HERMES_DISABLE_LAZY_INSTALLS=1 \
    HERMES_HOME=/sandbox/.hermes-data \
    GH_TOKEN=openshell:resolve:env:GITHUB_TOKEN

# Copy NemoClaw plugin for Hermes (Python-based)
COPY agents/hermes/plugins/nemoclaw/ /opt/nemoclaw-hermes-plugin/

# Copy nemo-relay plugin: in-process forwarder for pre/post_api_request
# events that enriches NeMo-Relay hook payloads with the real OpenAI request
# body and response body (the shell-hook path is metadata-only by design).
# Requires Hermes >= v0.14.0 because earlier versions sanitized plugin kwargs.
COPY agents/hermes/plugins/nemo-relay/ /opt/nemo-relay-hermes-plugin/

# Copy bridges and default cron jobs.
# Install under /usr/local/lib/ so Landlock's read_only /usr rule permits access.
COPY agents/hermes/bridges/ /usr/local/lib/nemoclaw-bridges/

# Copy config generation script and Slack helper shims.
# Install under /usr/local/lib so Landlock's read_only /usr rule permits
# the sandbox process to read both the decode proxy and preload files.
COPY agents/hermes/generate-config.ts /opt/nemoclaw-generate-config.ts
RUN mkdir -p /usr/local/lib/nemoclaw-slack-shims
COPY agents/hermes/decode-proxy.py /usr/local/lib/nemoclaw-slack-shims/decode-proxy.py
RUN chmod 755 /usr/local/lib/nemoclaw-slack-shims/decode-proxy.py \
    && find /usr/local/lib/nemoclaw-patches -type d -exec chmod 755 {} + \
    && find /usr/local/lib/nemoclaw-patches -type f -exec chmod 444 {} +

# NOTE: This example removes the upstream NemoClaw `COPY nemoclaw-blueprint/`
# step. Nothing in the Hermes runtime (start.sh, plugin/, bridges/, sidecars/,
# skills/) reads /sandbox/.nemoclaw/blueprints/0.1.0/ — it was build-time
# scaffolding only. Dropping it means the example doesn't need NemoClaw's
# nemoclaw-blueprint/ directory in its build context.

# Ensure sandbox user can read all /opt/nemoclaw-* and bridge files.
# Source files may have restrictive permissions that Docker COPY preserves.
RUN chmod -R a+rX /opt/nemoclaw-hermes-plugin/ \
    && chmod -R a+rX /opt/nemo-relay-hermes-plugin/ \
    && chmod a+r /opt/nemoclaw-generate-config.ts \
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
ARG SOURCE_ETL_API_HOST=host.openshell.internal
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

# Install nemo-relay plugin into Hermes. HERMES_HOME=/sandbox/.hermes-data
# (set in start.sh) and Hermes' plugin loader scans $HERMES_HOME/plugins/.
RUN mkdir -p /sandbox/.hermes-data/plugins/nemo-relay \
    && cp -r /opt/nemo-relay-hermes-plugin/* /sandbox/.hermes-data/plugins/nemo-relay/

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

# Interactive `hermes` invocations resolve through a PATH-prepended shim at
# /usr/local/lib/nemoclaw/bin/hermes (installed above). The shim blocks
# setup/doctor and execs the upstream binary; NEMO_RELAY_GATEWAY_URL in env
# carries telemetry to the sidecar.

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
