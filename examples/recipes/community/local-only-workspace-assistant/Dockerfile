# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Published NemoClaw OpenClaw sandbox image, pinned by digest. This is the
# digest that examples/recipes/nvidia/kubernetes-gpu-autoscaling uses for its
# OpenClaw and Ollama pairing.
ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/openclaw-sandbox@sha256:bd935f0198b99889d9479fea123b62a59e3797da13e392dcc2160f114216c1ba

FROM ${BASE_IMAGE}

# scripts/bring-up.sh passes both values from .env.
ARG INFERENCE_MODEL=nemotron-3-nano:4b-q4_K_M
ARG INFERENCE_BASE_URL=http://host.openshell.internal:11434/v1

# The base image configures OpenClaw for OpenShell 0.0: it sends model
# requests to the managed inference route (https://inference.local/v1) through
# an explicit proxy at 10.200.0.1:3128. OpenShell 0.1 removed both. It
# intercepts traffic without an explicit proxy, and it does not run the image
# entry point, so the start-up model override in the base image does not
# apply. Point the baked OpenClaw configuration at the recipe-owned Ollama
# server, turn off the explicit proxy, allow a slow CPU-only server up to ten
# minutes per request, and refresh the integrity hash that the base image keeps
# next to the configuration.
RUN python3 - "${INFERENCE_BASE_URL}" "${INFERENCE_MODEL}" <<'PY'
import hashlib, json, sys
from pathlib import Path

base_url, model = sys.argv[1], sys.argv[2]
config_path = Path("/sandbox/.openclaw/openclaw.json")
config = json.loads(config_path.read_text())
config["proxy"]["enabled"] = False
provider = config["models"]["providers"]["inference"]
provider["baseUrl"] = base_url
provider["timeoutSeconds"] = 600
for entry in provider["models"]:
    entry["id"] = model
    entry["name"] = "inference/" + model
config["agents"]["defaults"]["model"]["primary"] = "inference/" + model
config_path.write_text(json.dumps(config, indent=2) + "\n")
digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
Path("/sandbox/.openclaw/.config-hash").write_text("%s  %s\n" % (digest, config_path))
PY

ENV NEMOCLAW_MODEL=${INFERENCE_MODEL} \
    NEMOCLAW_PRIMARY_MODEL_REF=inference/${INFERENCE_MODEL} \
    NEMOCLAW_INFERENCE_BASE_URL=${INFERENCE_BASE_URL}

# Test canary. File permissions let every user read this file. The sandbox
# policy does not list /srv, so a read that succeeds inside the sandbox shows
# that the filesystem policy is not enforced. COPY keeps the base image user
# and entry point unchanged.
COPY --chmod=0644 fixtures/image/outside-canary.txt /srv/conformance/outside-canary.txt
