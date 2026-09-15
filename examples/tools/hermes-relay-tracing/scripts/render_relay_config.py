#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render the Relay observability configuration used by this tutorial."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_config(
    output_directory: Path,
    model_name: str,
    *,
    openinference_endpoint: str | None = None,
    openinference_project: str | None = None,
) -> str:
    root = output_directory.expanduser().resolve()
    config = f'''version = 1

[[components]]
kind = "observability"
enabled = true

[components.config]
version = 3
enable_full_payloads = false

[components.config.atof]
enabled = true

[[components.config.atof.sinks]]
type = "file"
output_directory = {toml_string(str(root / "atof"))}
filename = "run.jsonl"
mode = "overwrite"

[components.config.atif]
enabled = true
agent_name = "Hermes Agent"
model_name = {toml_string(model_name)}
output_directory = {toml_string(str(root / "atif"))}
filename_template = "trajectory-{{session_id}}.json"
'''
    if openinference_endpoint is None and openinference_project is None:
        return config
    if not openinference_endpoint or not openinference_endpoint.strip():
        raise ValueError("openinference_endpoint is required when exporting to Phoenix")
    if not openinference_project or not openinference_project.strip():
        raise ValueError("openinference_project is required when exporting to Phoenix")

    return config + f'''
[components.config.opentelemetry]
enabled = true

[[components.config.opentelemetry.endpoints]]
type = "openinference"
endpoint = {toml_string(openinference_endpoint.strip())}
transport = "http_binary"
service_name = "hermes-relay-tracing"
instrumentation_scope = "hermes-relay-tracing"
timeout_millis = 30000
# Keep this bounded tutorial run in one batch and flush it during Relay shutdown.
scheduled_delay_millis = 600000

[components.config.opentelemetry.endpoints.resource_attributes]
"openinference.project.name" = {toml_string(openinference_project.strip())}
'''


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render plugins.toml for the Hermes + NeMo Relay tutorial."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--openinference-endpoint")
    parser.add_argument("--openinference-project")
    args = parser.parse_args(argv)
    if not args.model_name.strip():
        parser.error("--model-name cannot be empty")
    if bool(args.openinference_endpoint) != bool(args.openinference_project):
        parser.error(
            "--openinference-endpoint and --openinference-project must be provided together"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_config(
            args.output_directory,
            args.model_name.strip(),
            openinference_endpoint=args.openinference_endpoint,
            openinference_project=args.openinference_project,
        ),
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
