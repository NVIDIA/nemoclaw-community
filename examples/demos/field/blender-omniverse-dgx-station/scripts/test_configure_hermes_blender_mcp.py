#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for profile-scoped Blender MCP configuration."""

from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

import yaml


SCRIPT = Path(__file__).with_name("configure_hermes_blender_mcp.py")
RAW_PROFILE_SCRIPT = Path(__file__).with_name("configure_blender_raw_profile.sh")
SPEC = importlib.util.spec_from_file_location("configure_hermes_blender_mcp", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigureHermesBlenderMcpTests(unittest.TestCase):
    def config_path(self, directory: str, content: dict) -> Path:
        path = Path(directory) / "config.yaml"
        path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
        return path

    def test_raw_profile_keeps_other_servers_and_adds_blender(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_path(
                directory,
                {"mcp_servers": {"other": {"url": "https://example.com/mcp"}}},
            )
            endpoint = MODULE.configure_profile(
                path, "10.176.172.12", include_workflow=False
            )
            configured = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(endpoint, "http://10.176.172.12:9877/mcp")
        self.assertIn("other", configured["mcp_servers"])
        self.assertEqual(
            configured["mcp_servers"]["blender"],
            {"url": "http://10.176.172.12:9877/mcp", "enabled": True},
        )

    def test_handoff_profile_replaces_inherited_servers_with_five_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_path(
                directory,
                {
                    "mcp_servers": {"blender": {"url": "http://host:9877/mcp"}},
                    "platforms": {"api_server": {"enabled": True}},
                },
            )
            endpoint = MODULE.configure_profile(
                path, "10.176.172.12", include_workflow=True
            )
            configured = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(endpoint, "http://10.176.172.12:9878/mcp")
        self.assertEqual(list(configured["mcp_servers"]), ["blender-workflow"])
        self.assertEqual(
            configured["mcp_servers"]["blender-workflow"]["tools"]["include"],
            MODULE.WORKFLOW_TOOLS,
        )
        self.assertFalse(configured["platforms"]["api_server"]["enabled"])

    def test_profile_is_required(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            MODULE.parser().parse_args(["10.176.172.12"])

    def test_raw_profile_becomes_the_plain_hermes_default(self) -> None:
        source = RAW_PROFILE_SCRIPT.read_text(encoding="utf-8")
        configure = (
            'python3 /sandbox/configure_hermes_blender_mcp.py "$HOST_IP" '
            '--profile "$PROFILE"'
        )
        select = 'hermes profile use "$PROFILE"'
        verify = "hermes mcp test blender"

        self.assertLess(source.index(configure), source.index(select))
        self.assertLess(source.index(select), source.index(verify))


if __name__ == "__main__":
    unittest.main()
