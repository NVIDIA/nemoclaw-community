#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add or update bounded Blender MCP endpoints in a named Hermes profile."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import yaml


WORKFLOW_TOOLS = [
    "capability_probe",
    "scene_inventory",
    "usd_export",
    "usd_inspect",
    "artifact_receipts",
]
HERMES_ROOT = Path("/sandbox/.hermes")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("host_ip")
    result.add_argument("--profile", required=True)
    result.add_argument("--include-workflow", action="store_true")
    return result


def validate_inputs(host_ip: str, profile: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", host_ip):
        raise SystemExit("host IP contains unsupported characters")
    if not re.fullmatch(r"[a-z0-9]+", profile):
        raise SystemExit("profile name must contain only lowercase letters and digits")


def configure_profile(
    config_path: Path, host_ip: str, *, include_workflow: bool
) -> str:
    if not config_path.is_file():
        raise SystemExit(f"Hermes configuration is unavailable: {config_path}")
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise SystemExit(f"Hermes configuration root must be a mapping: {config_path}")
    servers = cfg.get("mcp_servers")
    if not isinstance(servers, dict):
        servers = {}
        cfg["mcp_servers"] = servers
    if include_workflow:
        # The isolated handoff profile must not inherit the raw Blender MCP.
        # Hermes can surface MCP prompt/resource helpers through deferred
        # discovery even when tools.include restricts ordinary tool calls.
        servers.clear()
        servers["blender-workflow"] = {
            "url": f"http://{host_ip}:9878/mcp",
            "enabled": True,
            "tools": {"include": WORKFLOW_TOOLS},
        }
        platforms = cfg.setdefault("platforms", {})
        if not isinstance(platforms, dict):
            raise SystemExit("Hermes platforms configuration must be a mapping")
        api_server = platforms.setdefault("api_server", {})
        if not isinstance(api_server, dict):
            raise SystemExit("Hermes api_server configuration must be a mapping")
        api_server["enabled"] = False
    else:
        servers["blender"] = {
            "url": f"http://{host_ip}:9877/mcp",
            "enabled": True,
        }
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return f"http://{host_ip}:{9878 if include_workflow else 9877}/mcp"


def main() -> int:
    args = parser().parse_args()
    validate_inputs(args.host_ip, args.profile)
    config_path = HERMES_ROOT / "profiles" / args.profile / "config.yaml"
    endpoint = configure_profile(
        config_path, args.host_ip, include_workflow=args.include_workflow
    )
    print(f"configured {endpoint} in {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
