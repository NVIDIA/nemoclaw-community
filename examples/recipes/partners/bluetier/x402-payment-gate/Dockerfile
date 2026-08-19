# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Reproducible sandbox image for the x402-payment-gate recipe: the pinned
# NemoClaw Hermes base plus this recipe's skill and stdlib client baked into
# the immutable skills directory.
#
# IMPORTANT -- build context is the RECIPE ROOT (this file's directory), not a
# sub-directory. The COPY paths below (agents/, scripts/) are resolved against
# the recipe root, so both `openshell sandbox create --from <recipe-root>` and a
# plain `docker build` must run with the recipe root as context:
#
#   docker build -t x402-payment-gate-sandbox .        # from the recipe root
#   openshell sandbox create --from <recipe-root> ...  # OpenShell builds it
#
# (This is why the Dockerfile lives at the recipe root, not under sandbox/:
# `openshell --from` uses the Dockerfile's own directory as the build context,
# so the Dockerfile and the files it COPYs must share one root. See .dockerignore
# for what is kept out of that context.)
#
# Zero-build alternative: policy.yaml sets include_workdir: true, so running
# the sandbox with this example directory as the workdir exposes the same
# files without a custom image; the baked copy is the reproducible path.
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/hermes-sandbox-base@sha256:fa05221f5c7bcafea7e263c84e5d06f87e37d1ccb78dc28c113f1a4066aa544c
FROM ${BASE_IMAGE}

COPY agents/hermes/skills/blackwall-payment-gate/ /sandbox/.hermes/skills/blackwall-payment-gate/
COPY scripts/blackwall_client.py scripts/demo_verdicts.py /sandbox/.hermes/skills/blackwall-payment-gate/scripts/
