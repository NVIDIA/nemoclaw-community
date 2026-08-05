# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compatibility contracts for the example-owned NeMo Relay bridge."""

from __future__ import annotations

import importlib.util
import json
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


class NemoRelayForwardSanitizationTest(unittest.TestCase):
    def test_forward_sanitizes_openshell_env_placeholders(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def post(self, url: str, json: dict) -> None:
                self.calls.append((url, json))

        client = FakeClient()
        payload = {
            "hook_event_name": "pre_api_request",
            "request": {
                "body": {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "keep this text but hide "
                                "openshell:resolve:env:FAKE_TOKEN"
                            ),
                        }
                    ]
                }
            },
            "metadata": ("openshell:resolve:env:ANOTHER_TOKEN",),
        }

        with (
            mock.patch.object(
                PLUGIN, "_gateway_url", return_value="http://relay.local"
            ),
            mock.patch.object(PLUGIN, "_client", return_value=client),
        ):
            PLUGIN._forward(payload)

        self.assertEqual(
            client.calls,
            [
                (
                    "http://relay.local/hooks/hermes",
                    {
                        "hook_event_name": "pre_api_request",
                        "request": {
                            "body": {
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": (
                                            "keep this text but hide "
                                            "[openshell env placeholder]"
                                        ),
                                    }
                                ]
                            }
                        },
                        "metadata": ["[openshell env placeholder]"],
                    },
                )
            ],
        )
        self.assertNotIn("openshell:resolve:env:", json.dumps(client.calls[0][1]))
        self.assertEqual(
            payload["metadata"],
            ("openshell:resolve:env:ANOTHER_TOKEN",),
        )

    def test_sanitizer_preserves_noncanonical_lookalikes(self) -> None:
        lookalikes = {
            "wrong_case": "OpenShell:resolve:env:FAKE_TOKEN",
            "wrong_kind": "openshell:resolve:file:FAKE_TOKEN",
            "invalid_name": "openshell:resolve:env:9_FAKE_TOKEN",
        }

        self.assertEqual(
            PLUGIN._sanitize_open_shell_placeholders(lookalikes),
            lookalikes,
        )


if __name__ == "__main__":
    unittest.main()
