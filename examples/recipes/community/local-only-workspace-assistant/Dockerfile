# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Published NemoClaw OpenClaw sandbox image, pinned by digest. This is the
# digest that examples/recipes/nvidia/kubernetes-gpu-autoscaling uses for its
# OpenClaw and Ollama pairing.
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/openclaw-sandbox@sha256:bd935f0198b99889d9479fea123b62a59e3797da13e392dcc2160f114216c1ba

FROM ${BASE_IMAGE}

# Test canary. File permissions let every user read this file. The sandbox
# policy does not list /srv, so a read that succeeds inside the sandbox shows
# that the filesystem policy is not enforced. COPY keeps the base image user
# and entry point unchanged.
COPY --chmod=0644 fixtures/image/outside-canary.txt /srv/conformance/outside-canary.txt
