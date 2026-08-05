#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the bounded Blender workflow MCP protocol and path gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("blender_workflow_mcp_server.py")
SPEC = importlib.util.spec_from_file_location("blender_workflow_mcp_server", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class BlenderWorkflowMcpServerTests(unittest.TestCase):
    def test_initialize_and_tool_list_are_valid_mcp_results(self) -> None:
        initialized = SERVER._handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "blender-workflow")

        listed = SERVER._handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "capability_probe",
                "scene_inventory",
                "usd_export",
                "usd_inspect",
                "artifact_receipts",
            },
        )
        descriptions = {tool["name"]: tool["description"] for tool in listed["result"]["tools"]}
        self.assertIn("required output_path", descriptions["usd_export"])

    def test_write_path_outside_configured_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(SERVER, "WRITE_ROOTS", [Path(directory).resolve()]):
                with self.assertRaisesRegex(ValueError, "outside the allowed roots"):
                    SERVER._validated_request(
                        "usd_export", {"output_path": "/tmp/not-allowed.usda"}
                    )

    def test_successful_tool_call_returns_compact_json_content(self) -> None:
        expected = {
            "status": "pass",
            "action": "capability_probe",
            "result": {"ovrtx_available": True},
        }
        with mock.patch.object(SERVER, "_call_blender", return_value=expected):
            response = SERVER._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "capability_probe", "arguments": {}},
                }
            )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), expected)

    def test_invalid_arguments_are_repairable_without_opening_circuit_breaker(self) -> None:
        with mock.patch.object(SERVER, "_call_blender") as call_blender:
            response = SERVER._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "usd_export",
                        "arguments": {"path": "/tmp/guessed-field.usda"},
                    },
                }
            )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"])["status"],
            "invalid_arguments",
        )
        call_blender.assert_not_called()

    def test_blocked_receipt_is_an_mcp_tool_error(self) -> None:
        blocked = {"status": "blocked", "error": "capability unavailable"}
        with mock.patch.object(SERVER, "_call_blender", return_value=blocked):
            response = SERVER._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "capability_probe", "arguments": {}},
                }
            )
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
