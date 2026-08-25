# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


RECIPE_DIR = Path(__file__).resolve().parents[2]
SCRIPT = RECIPE_DIR / "scripts/slack_delivery_diagnostic.py"
INSTRUMENTATION = RECIPE_DIR / "agents/hermes/patches/slack_diagnostic.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DIAGNOSTIC = load_module("slack_delivery_diagnostic", SCRIPT)
INSTRUMENT = load_module("slack_diagnostic_instrumentation", INSTRUMENTATION)


def stage(name: str, status: str = "confirmed", timestamp: float = 100.0):
    return {
        "diagnostic_id": "NC-1234ABCD",
        "stage": name,
        "status": status,
        "timestamp": timestamp,
    }


class SlackDeliveryEvaluationTest(TestCase):
    def test_success_confirms_complete_delivery_path(self) -> None:
        result = DIAGNOSTIC.evaluate_delivery(
            [
                stage("inbound_event_receipt"),
                stage("hermes_dispatch"),
                stage("inference", "started"),
                stage("inference"),
                stage("outbound_response"),
            ],
            timed_out=False,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["last_stage"], "outbound_response")

    def test_timeout_after_dispatch_identifies_inference(self) -> None:
        result = DIAGNOSTIC.evaluate_delivery(
            [
                stage("inbound_event_receipt"),
                stage("hermes_dispatch"),
                stage("inference", "started"),
            ],
            timed_out=True,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["category"], "inference_timeout")
        self.assertEqual(result["last_stage"], "hermes_dispatch")

    def test_missing_inbound_event_stops_at_socket_mode(self) -> None:
        result = DIAGNOSTIC.evaluate_delivery([], timed_out=True)

        self.assertEqual(result["category"], "missing_inbound_event")
        self.assertEqual(result["last_stage"], "socket_mode_connection")

    def test_inference_failure_stops_at_dispatch(self) -> None:
        result = DIAGNOSTIC.evaluate_delivery(
            [
                stage("inbound_event_receipt"),
                stage("hermes_dispatch"),
                stage("inference", "failed"),
            ],
            timed_out=False,
        )

        self.assertEqual(result["category"], "inference_failure")
        self.assertEqual(result["last_stage"], "hermes_dispatch")

    def test_outbound_failure_stops_at_inference(self) -> None:
        result = DIAGNOSTIC.evaluate_delivery(
            [
                stage("inbound_event_receipt"),
                stage("hermes_dispatch"),
                stage("inference"),
                stage("outbound_response", "failed", 100.0),
            ],
            timed_out=False,
            now=103.0,
        )

        self.assertEqual(result["category"], "outbound_response_failure")
        self.assertEqual(result["last_stage"], "inference")

    def test_allowlist_description_does_not_print_member_ids(self) -> None:
        description = DIAGNOSTIC.authorization_description("U123,U456")

        self.assertEqual(description, "explicit allowlist (2 members)")
        self.assertNotIn("U123", description)
        self.assertEqual(
            DIAGNOSTIC.authorization_description(""),
            "allow-all (no SLACK_ALLOWED_IDS value)",
        )


class SlackDeliveryInstrumentationTest(TestCase):
    def test_stage_log_keeps_only_sanitized_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "diagnostic.jsonl"
            with patch.object(INSTRUMENT, "DIAGNOSTIC_LOG", log_path):
                INSTRUMENT.record_stage(
                    "private text NC-1234ABCD unrelated text",
                    "inference",
                    status="failed",
                    error_type="RuntimeError",
                )

            event = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(event),
                {
                    "diagnostic_id",
                    "stage",
                    "status",
                    "timestamp",
                    "pid",
                    "error_type",
                },
            )
            self.assertEqual(event["diagnostic_id"], "NC-1234ABCD")
            self.assertNotIn("private text", repr(event))
            self.assertNotIn("unrelated text", repr(event))
            self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)

    def test_adapter_hooks_record_stages_without_message_content(self) -> None:
        class FakeAdapter:
            async def _handle_slack_message(self, event, payload=None):
                return None

            async def _handle_slash_command(self, command):
                return None

            async def handle_message(self, event):
                return None

            def set_message_handler(self, handler):
                self._message_handler = handler

            async def send(self, chat_id, content, reply_to=None, metadata=None):
                return SimpleNamespace(success=True)

        private_text = "private request NC-1234ABCD with unrelated content"
        event = SimpleNamespace(
            text=private_text,
            source=SimpleNamespace(chat_id="D123", thread_id="171.001"),
            metadata={
                "slack_team_id": "T123",
                "slack_channel_id": "D123",
                "slack_thread_ts": "171.001",
            },
            message_id="171.001",
        )

        self.assertTrue(INSTRUMENT.install_adapter_instrumentation(FakeAdapter))
        adapter = FakeAdapter()

        async def handler(message):
            return "response"

        with patch.object(INSTRUMENT, "record_stage") as record:
            adapter.set_message_handler(handler)
            asyncio.run(adapter._handle_slack_message({"text": private_text}))
            asyncio.run(adapter.handle_message(event))
            asyncio.run(adapter._message_handler(event))
            asyncio.run(
                adapter.send(
                    "D123",
                    "response",
                    metadata={
                        "slack_team_id": "T123",
                        "slack_thread_ts": "171.001",
                    },
                )
            )

        serialized_calls = repr(record.call_args_list)
        self.assertIn("inbound_event_receipt", serialized_calls)
        self.assertIn("hermes_dispatch", serialized_calls)
        self.assertIn("inference", serialized_calls)
        self.assertIn("outbound_response", serialized_calls)
        self.assertNotIn("private request", serialized_calls)
        self.assertNotIn("unrelated content", serialized_calls)


if __name__ == "__main__":
    import unittest

    unittest.main()
