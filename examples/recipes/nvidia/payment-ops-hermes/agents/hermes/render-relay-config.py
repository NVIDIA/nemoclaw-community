#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render the image's NeMo Relay configuration from build-time environment."""

import json
import os
from pathlib import Path

template = Path("/tmp/plugins.toml.in").read_text(encoding="utf-8")
endpoint = os.environ.get("PHOENIX_URL", "").strip().rstrip("/")
project = os.environ.get("PROJECT", "").strip()
attributes = ""
if endpoint and project:
    quoted = json.dumps(project)
    attributes = "\n".join(
        (
            "[components.config.openinference.resource_attributes]",
            f'"openinference.project.name" = {quoted}',
            f'"nemo.claw.example" = {quoted}',
        )
    )
rendered = (
    template.replace("@@PHOENIX_ENABLED@@", str(bool(endpoint)).lower())
    .replace("@@PHOENIX_ENDPOINT@@", json.dumps(endpoint))
    .replace("@@OPENINFERENCE_RESOURCE_ATTRIBUTES@@", attributes)
)
output = Path("/etc/nemo-relay/plugins.toml")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(rendered, encoding="utf-8")
