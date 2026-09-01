# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# NemoClaw Hermes base from the latest published tag v0.0.94 at
# d87acc16b04c065ddc26c294a6c3af6795a43d7b (Hermes v2026.7.1 / package
# v0.18.0). Update this digest only after reviewing a newer published tag.
ARG BASE_IMAGE=
FROM ${BASE_IMAGE}
ARG HERMES_VERSION=

USER root

RUN test "$(/opt/hermes/.venv/bin/python -c \
      'from importlib.metadata import version; print(version("hermes-agent"))')" \
    = "$HERMES_VERSION"

COPY agents/hermes/generate-config.ts /opt/review-advisor/generate-config.ts
COPY agents/hermes/start.sh /usr/local/bin/review-advisor-start
COPY agents/hermes/probe-inference.py /opt/review-advisor/probe-inference.py
COPY agents/hermes/record-feedback.py /opt/review-advisor/record-feedback.py
COPY agents/hermes/SOUL.md /opt/review-advisor/SOUL.md
COPY agents/hermes/plugins/review-advisor/ /opt/review-advisor/plugin/
COPY skills/pr-review/ /opt/review-advisor/skill/
COPY schemas/ /opt/review-advisor/schemas/
COPY review-profiles/ /opt/review-advisor/profiles/

ARG REVIEW_ADVISOR_RUNTIME_FINGERPRINT=UNSET
RUN case "$REVIEW_ADVISOR_RUNTIME_FINGERPRINT" in \
      *[!0-9a-f]*|'') echo "invalid runtime fingerprint" >&2; exit 1 ;; \
    esac \
    && test "${#REVIEW_ADVISOR_RUNTIME_FINGERPRINT}" -eq 64 \
    && printf '%s\n' "$REVIEW_ADVISOR_RUNTIME_FINGERPRINT" \
        >/opt/review-advisor/runtime-fingerprint \
    && chmod 444 /opt/review-advisor/runtime-fingerprint \
    && chmod 755 /usr/local/bin/review-advisor-start /opt/review-advisor/record-feedback.py \
    && chmod -R a+rX /opt/review-advisor \
    && mkdir -p /sandbox/.hermes/plugins/review-advisor \
        /sandbox/.hermes/skills/pr-review \
        /sandbox/.hermes/memories \
        /sandbox/.hermes/sessions \
        /sandbox/review-input \
        /sandbox/review-staging \
    && cp -a /opt/review-advisor/plugin/. /sandbox/.hermes/plugins/review-advisor/ \
    && cp -a /opt/review-advisor/skill/. /sandbox/.hermes/skills/pr-review/ \
    && cp /opt/review-advisor/SOUL.md /sandbox/.hermes/SOUL.md \
    && chown -R sandbox:sandbox /sandbox/.hermes /sandbox/review-input /sandbox/review-staging \
    && chmod 700 /sandbox/review-input /sandbox/review-staging

ARG NEMOCLAW_MODEL=nvidia/nemotron-3-ultra-550b-a55b
ENV NEMOCLAW_MODEL=${NEMOCLAW_MODEL} \
    REVIEW_ADVISOR_RUNTIME_FINGERPRINT=${REVIEW_ADVISOR_RUNTIME_FINGERPRINT} \
    NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1 \
    HERMES_HOME=/sandbox/.hermes \
    HERMES_DISABLE_LAZY_INSTALLS=1 \
    REVIEW_ADVISOR_REPO_ROOT=/sandbox/review-input/repo \
    REVIEW_ADVISOR_CONTEXT_FILE=/sandbox/review-input/context.json \
    REVIEW_ADVISOR_PROFILE_FILE=/sandbox/review-input/profile.yaml \
    REVIEW_ADVISOR_ATTESTATION_KEY_FILE=/sandbox/review-input/attestation.key \
    PATH=/usr/local/bin:/opt/hermes/.venv/bin:${PATH}

USER sandbox
WORKDIR /sandbox
RUN node --experimental-strip-types /opt/review-advisor/generate-config.ts \
    && /opt/hermes/.venv/bin/python -m compileall -q \
        /sandbox/.hermes/plugins/review-advisor

EXPOSE 8642
ENTRYPOINT ["/usr/local/bin/review-advisor-start"]
