# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compatibility contracts for the example-owned NeMo Relay bridge."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "plugins" / "nemo-relay" / "__init__.py"
)
SPEC = importlib.util.spec_from_file_location(
    "community_nemo_relay_plugin", PLUGIN_PATH
)
assert SPEC is not None and SPEC.loader is not None
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class NemoRelayPluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.forwarded: list[dict] = []
        self.forward_patch = mock.patch.object(
            PLUGIN, "_forward", side_effect=self.forwarded.append
        )
        self.forward_patch.start()
        PLUGIN._PENDING_PRE.clear()

    def tearDown(self) -> None:
        self.forward_patch.stop()
        PLUGIN._PENDING_PRE.clear()

    def test_prefers_hermes_018_sanitized_request(self) -> None:
        request = {
            "method": "POST",
            "body": {
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test/model",
                "max_tokens": 128,
                "tools": [{"type": "function"}],
            },
        }

        PLUGIN.on_pre_api_request(
            task_id="task-1",
            request=request,
            request_messages=[{"role": "user", "content": "legacy"}],
        )

        self.assertEqual(len(self.forwarded), 1)
        self.assertEqual(self.forwarded[0]["request"], request)

    def test_reads_hermes_018_sanitized_response_fields(self) -> None:
        PLUGIN.on_post_api_request(
            task_id="task-1",
            response={
                "model": "test/model-resolved",
                "finish_reason": "stop",
                "assistant_message": {
                    "role": "assistant",
                    "content": "hello back",
                    "tool_calls": [],
                },
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            },
        )

        self.assertEqual(len(self.forwarded), 1)
        response = self.forwarded[0]["response"]
        self.assertIsNone(response["raw_response"])
        self.assertEqual(response["assistant_message"]["content"], "hello back")
        self.assertEqual(response["model"], "test/model-resolved")
        self.assertEqual(response["finish_reason"], "stop")
        self.assertEqual(response["usage"]["total_tokens"], 10)

    def test_retains_legacy_raw_provider_response(self) -> None:
        raw_response = SimpleNamespace(
            id="response-1",
            model="legacy/model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="legacy response"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(total_tokens=4),
        )

        PLUGIN.on_post_api_request(task_id="task-1", response=raw_response)

        response = self.forwarded[0]["response"]
        self.assertEqual(response["raw_response"]["id"], "response-1")
        self.assertEqual(
            response["raw_response"]["choices"][0]["message"]["content"],
            "legacy response",
        )

    def test_pre_and_post_tool_events_share_one_id(self) -> None:
        PLUGIN.on_pre_tool_call(
            task_id="task-1",
            tool_name="search",
            args={"query": "tables"},
            tool_call_id="",
        )
        PLUGIN.on_post_tool_call(
            task_id="task-1",
            tool_name="search",
            args={"query": "tables"},
            result={"ok": True},
            tool_call_id="provider-id",
        )

        self.assertEqual(len(self.forwarded), 2)
        self.assertEqual(
            self.forwarded[0]["tool_call_id"],
            self.forwarded[1]["tool_call_id"],
        )
        self.assertEqual(PLUGIN._PENDING_PRE, {})


if __name__ == "__main__":
    unittest.main()
