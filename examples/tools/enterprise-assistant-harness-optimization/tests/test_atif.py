# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import hashlib
import unittest

from pa_style_mock_mcp.atif import extract_run


class AtifExtractionTest(unittest.TestCase):
    def test_extracts_hermes_mcp_names_and_replays_write_state(self) -> None:
        token_input = "mail|ava.patel@example.test|Please send the packet.|0"
        approval_token = f"approval_{hashlib.sha256(token_input.encode()).hexdigest()[:12]}"
        atif = {
            "schema_version": "ATIF-v1.7",
            "session_id": "fictional-session",
            "steps": [
                {
                    "source": "agent",
                    "tool_calls": [
                        {"function_name": "mcp__pa_style_enterprise__actions_prepare_message", "arguments": {"channel": "mail", "recipient": "ava.patel@example.test", "body": "Please send the packet."}}
                    ],
                },
                {
                    "source": "agent",
                    "tool_calls": [
                        {"function_name": "mcp__pa_style_enterprise__actions_send_message", "arguments": {"approval_token": approval_token}}
                    ],
                },
                {"source": "agent", "message": "The approved message was sent."},
            ],
        }
        run = extract_run("write-case", atif)
        self.assertEqual([call["name"] for call in run["calls"]], ["actions.prepare_message", "actions.send_message"])
        self.assertEqual(run["outbox"][0]["recipient"], "ava.patel@example.test")
        self.assertEqual(run["final_answer"], "The approved message was sent.")
        self.assertEqual([result["ok"] for result in run["tool_results"]], [True, True])

    def test_extract_marks_replayed_tool_error_without_counting_it_as_success(self) -> None:
        atif = {
            "schema_version": "ATIF-v1.7",
            "session_id": "fictional-session",
            "steps": [{"tool_calls": [{"function_name": "mcp__pa_style_enterprise__connectors_get_status", "arguments": {}}]}],
        }
        run = extract_run("bad-arguments", atif)
        self.assertEqual(run["tool_results"], [{"name": "connectors.get_status", "ok": False, "error_code": "INVALID_ARGUMENTS"}])

    def test_rejects_non_demo_tools(self) -> None:
        atif = {"schema_version": "ATIF-v1.7", "steps": [{"tool_calls": [{"function_name": "terminal", "arguments": {}}]}]}
        with self.assertRaisesRegex(ValueError, "unknown or non-demo tool"):
            extract_run("bad", atif)

    def test_replays_walkthrough_mcp_server_prefix(self) -> None:
        atif = {
            "schema_version": "ATIF-v1.7",
            "steps": [
                {
                    "tool_calls": [
                        {
                            "function_name": "mcp__enterprise_world__chat_search",
                            "arguments": {"query": "launch"},
                        }
                    ]
                }
            ],
        }

        run = extract_run("walkthrough-prefix", atif)

        self.assertEqual(run["calls"][0]["name"], "chat.search")
