#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outlook_finance_bridge as bridge


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outlook-emails.json"


def arguments(**overrides: object) -> argparse.Namespace:
    values = {
        "fixture": FIXTURE,
        "limit": 5,
        "include_read": False,
        "base_url": "http://127.0.0.1:8642/v1",
        "timeout": 10,
        "reply_mode": "print",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class OutlookFinanceBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "OUTLOOK_TARGET_MAILBOX": "agent@example.com",
                "OUTLOOK_REPLY_TO": "pm@northstar-cap.com",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    @patch("outlook_finance_bridge.ask_agent", return_value="draft")
    def test_fixture_rejects_every_sender_except_reply_to(self, _ask: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = bridge.process_messages(
                arguments(), set(), Path(directory) / "processed.json"
            )
        self.assertEqual([result["id"] for result in results], ["fixture-nvda-brief"])

    def test_state_write_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processed.json"
            bridge.save_processed(path, {"b", "a"})
            self.assertEqual(bridge.load_processed(path), {"a", "b"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @patch("outlook_finance_bridge.mark_read")
    @patch("outlook_finance_bridge.reply_graph", side_effect=RuntimeError("failed"))
    @patch("outlook_finance_bridge.ask_agent", return_value="draft")
    def test_graph_reply_records_intent_before_network_side_effect(
        self, _ask: object, _reply: object, _mark: object
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processed.json"
            with self.assertRaisesRegex(RuntimeError, "failed"):
                bridge.process_messages(arguments(reply_mode="graph"), set(), path)
            self.assertEqual(bridge.load_processed(path), {"fixture-nvda-brief"})

    @patch("outlook_finance_bridge.ask_agent", return_value="")
    def test_empty_agent_reply_is_never_sent(self, _ask: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "empty Outlook reply"):
                bridge.process_messages(
                    arguments(reply_mode="graph"),
                    set(),
                    Path(directory) / "processed.json",
                )

    @patch("outlook_finance_bridge.graph_request")
    def test_graph_loader_uses_full_text_body(self, graph_request: object) -> None:
        full_body = "x" * 600
        graph_request.return_value = {
            "value": [
                {
                    "id": "message",
                    "from": {"emailAddress": {"address": "pm@northstar-cap.com"}},
                    "subject": "Long request",
                    "body": {"contentType": "text", "content": full_body},
                    "bodyPreview": full_body[:255],
                    "isRead": False,
                }
            ]
        }
        messages = bridge.load_graph_messages(1)
        self.assertEqual(messages[0]["body"], full_body)
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(graph_request.call_args.args[0]).query
        )
        self.assertIn("body,bodyPreview", query["$select"][0])


if __name__ == "__main__":
    unittest.main()
