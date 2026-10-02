# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import unittest

from pa_style_mock_mcp import ToolRegistry
from pa_style_mock_mcp.mcp_stdio import handle


class McpStdioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()

    def test_tools_are_discoverable(self) -> None:
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.registry)
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("chat.search", names)
        self.assertIn("actions.send_message", names)

    def test_tool_result_uses_mcp_content_shape(self) -> None:
        response = handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "connectors.get_status", "arguments": {"connector": "crm"}}},
            self.registry,
        )
        content = response["result"]["content"]
        payload = json.loads(content[0]["text"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "needs_auth")

    def test_initialized_notification_has_no_response(self) -> None:
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.registry))

    def test_extended_catalog_has_more_real_tools(self) -> None:
        response = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, ToolRegistry(catalog="extended"))
        self.assertEqual(len(response["result"]["tools"]), 15)
