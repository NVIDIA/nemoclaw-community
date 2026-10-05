# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import unittest

from pa_style_mock_mcp.atif import atof_events_to_atif_trajectories


class AtofToAtifTests(unittest.TestCase):
    def test_preserves_recorded_prompt_tool_result_and_normalization_loss(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:00+00:00"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {"content": {"messages": [{"role": "user", "content": "Find it"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {"model": "nemotron", "usage": {"prompt_tokens": 10, "completion_tokens": 3}, "choices": [{"message": {"content": "Found it"}}]}},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "search", "uuid": "tool", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:02+00:00", "data": {"query": "it"}, "metadata": {"tool_call_id": "call-1"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "search", "uuid": "tool", "parent_uuid": "turn", "data": {"ok": True}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:04+00:00", "data": {"outcome": "success"}},
        ]

        trajectory = atof_events_to_atif_trajectories(events)[0]

        self.assertEqual(trajectory["schema_version"], "ATIF-v1.7")
        self.assertEqual(trajectory["steps"][0]["message"], "Find it")
        self.assertEqual(trajectory["steps"][1]["tool_calls"][0]["tool_call_id"], "call-1")
        self.assertIn("ATOF scope nesting", trajectory["extra"]["normalization"]["losses"][0])
        self.assertEqual(trajectory["steps"][-1]["message"], "Found it")

    def test_public_mode_redacts_only_non_fixture_tool_payloads(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "read_file", "uuid": "local", "parent_uuid": "turn", "data": {"path": "/private"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "read_file", "uuid": "local", "parent_uuid": "turn", "data": "private data"},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "mcp__pa_style_enterprise__chat_search", "uuid": "fixture", "parent_uuid": "turn", "data": {"query": "launch"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "mcp__pa_style_enterprise__chat_search", "uuid": "fixture", "parent_uuid": "turn", "data": {"ok": True}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "success"}},
        ]

        trajectory = atof_events_to_atif_trajectories(
            events, redact_non_fixture_tools=True
        )[0]

        self.assertEqual(
            trajectory["steps"][1]["tool_calls"][0]["arguments"]["redacted"],
            "non-fixture tool input removed for public bundle",
        )
        self.assertIn("[redacted:", trajectory["steps"][1]["observation"]["results"][0]["content"])
        self.assertEqual(
            trajectory["steps"][2]["tool_calls"][0]["arguments"], {"query": "launch"}
        )
        self.assertIn("fixture tool inputs", trajectory["extra"]["normalization"]["losses"][1])


if __name__ == "__main__":
    unittest.main()
