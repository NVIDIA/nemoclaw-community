# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
EXAMPLES = Path(__file__).parents[1] / "examples"
sys.path.insert(0, str(SCRIPTS))

import summarize_atof


class SummarizeAtofTests(unittest.TestCase):
    def test_main_prints_token_usage_only_when_requested(self) -> None:
        trace = str(EXAMPLES / "terminal-task.atof.jsonl")
        default_output = StringIO()
        required_output = StringIO()

        with redirect_stdout(default_output):
            self.assertEqual(summarize_atof.main([trace]), 0)
        with redirect_stdout(required_output):
            self.assertEqual(
                summarize_atof.main([trace, "--require-token-usage"]), 0
            )

        self.assertNotIn("total tokens", default_output.getvalue())
        self.assertIn("total tokens: 120", required_output.getvalue())

    def test_example_trace_summarizes_the_terminal_task(self) -> None:
        events = summarize_atof.load_events(EXAMPLES / "terminal-task.atof.jsonl")
        summary = summarize_atof.summarize(events)

        self.assertEqual(
            summary,
            {
                "events": 5,
                "completed_llm_scopes": 1,
                "llm_scopes_with_usage": 1,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "tool_calls": 1,
                "tool_errors": 0,
                "correlated_events": 5,
            },
        )

        llm_end = next(
            event
            for event in events
            if event.get("category") == "llm"
            and event.get("scope_category") == "end"
        )
        self.assertEqual(
            llm_end["data"]["usage"],
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )

    def test_summarize_counts_completed_scopes_and_tools(self) -> None:
        events = [
            {"kind": "scope", "category": "llm", "scope_category": "end", "uuid": "llm"},
            {"kind": "scope", "category": "tool", "scope_category": "start", "uuid": "tool"},
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "end",
                "uuid": "tool",
                "metadata": {"otel.status_code": "ERROR"},
            },
        ]

        self.assertEqual(
            summarize_atof.summarize(events),
            {
                "events": 3,
                "completed_llm_scopes": 1,
                "llm_scopes_with_usage": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "tool_calls": 1,
                "tool_errors": 1,
                "correlated_events": 3,
            },
        )

    def test_summarize_uses_terminal_chunk_usage_for_completed_llm_scope(self) -> None:
        events = [
            {
                "kind": "mark",
                "name": "llm.chunk",
                "parent_uuid": "llm",
                "data": {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                    }
                },
            },
            {
                "kind": "scope",
                "category": "llm",
                "scope_category": "end",
                "uuid": "llm",
                "data": {"usage": None},
            },
        ]

        summary = summarize_atof.summarize(events)

        self.assertEqual(summary["llm_scopes_with_usage"], 1)
        self.assertEqual(summary["prompt_tokens"], 100)
        self.assertEqual(summary["completion_tokens"], 20)
        self.assertEqual(summary["total_tokens"], 120)

    def test_summarize_prefers_scope_usage_over_chunk_usage(self) -> None:
        events = [
            {
                "kind": "mark",
                "name": "llm.chunk",
                "parent_uuid": "llm",
                "data": {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                    }
                },
            },
            {
                "kind": "scope",
                "category": "llm",
                "scope_category": "end",
                "uuid": "llm",
                "data": {
                    "usage": {
                        "prompt_tokens": 110,
                        "completion_tokens": 25,
                    }
                },
            },
        ]

        summary = summarize_atof.summarize(events)

        self.assertEqual(summary["llm_scopes_with_usage"], 1)
        self.assertEqual(summary["prompt_tokens"], 110)
        self.assertEqual(summary["completion_tokens"], 25)
        self.assertEqual(summary["total_tokens"], 135)

    def test_summarize_does_not_treat_provider_specific_usage_as_complete(self) -> None:
        events = [
            {
                "kind": "scope",
                "category": "llm",
                "scope_category": "end",
                "uuid": "llm",
                "data": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 531,
                        "cache_read_input_tokens": 43552,
                        "cache_creation_input_tokens": 15976,
                    }
                },
            }
        ]

        summary = summarize_atof.summarize(events)

        self.assertEqual(summary["llm_scopes_with_usage"], 0)
        self.assertEqual(summary["total_tokens"], 0)

    def test_validate_trace_requirements_rejects_missing_llm_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "completed LLM scope"):
            summarize_atof.validate_trace_requirements(
                [],
                {
                    "completed_llm_scopes": 0,
                    "tool_calls": 1,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=[],
            )

    def test_validate_trace_accepts_required_tool_command(self) -> None:
        events = summarize_atof.load_events(EXAMPLES / "terminal-task.atof.jsonl")

        summarize_atof.validate_trace_requirements(
            events,
            summarize_atof.summarize(events),
            require_llm=True,
            require_tool=True,
            require_no_tool_errors=True,
            required_tool_command="sample.py",
            required_tool_names=[],
        )

    def test_validate_trace_requirements_rejects_missing_tool_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "tool call"):
            summarize_atof.validate_trace_requirements(
                [],
                {
                    "completed_llm_scopes": 1,
                    "tool_calls": 0,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=[],
            )

    def test_validate_trace_requirements_rejects_missing_token_usage(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive LLM token usage"):
            summarize_atof.validate_trace_requirements(
                [],
                {
                    "completed_llm_scopes": 1,
                    "total_tokens": 0,
                    "tool_calls": 1,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=[],
                require_token_usage=True,
            )

    def test_validate_trace_requirements_rejects_tool_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "error-free tool calls"):
            summarize_atof.validate_trace_requirements(
                [],
                {
                    "completed_llm_scopes": 1,
                    "tool_calls": 1,
                    "tool_errors": 1,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=[],
            )

    def test_validate_trace_rejects_missing_required_tool_command(self) -> None:
        events = [
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "start",
                "data": {"command": "python3 another_file.py"},
            }
        ]

        with self.assertRaisesRegex(ValueError, "sample.py"):
            summarize_atof.validate_trace_requirements(
                events,
                {
                    "completed_llm_scopes": 1,
                    "tool_calls": 1,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command="sample.py",
                required_tool_names=[],
            )

    def test_validate_trace_accepts_required_tool_name(self) -> None:
        events = [
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "start",
                "uuid": "web-search",
                "name": "web_search",
            },
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "end",
                "uuid": "web-search",
                "metadata": {"otel.status_code": "OK"},
            },
        ]

        summarize_atof.validate_trace_requirements(
            events,
            {
                "completed_llm_scopes": 1,
                "tool_calls": 1,
                "tool_errors": 0,
            },
            require_llm=True,
            require_tool=True,
            require_no_tool_errors=True,
            required_tool_command=None,
            required_tool_names=["web_search"],
        )

    def test_validate_trace_rejects_missing_required_tool_name(self) -> None:
        events = [
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "start",
                "uuid": "terminal",
                "name": "terminal",
            },
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "end",
                "uuid": "terminal",
                "metadata": {"otel.status_code": "OK"},
            },
        ]

        with self.assertRaisesRegex(ValueError, "web_search"):
            summarize_atof.validate_trace_requirements(
                events,
                {
                    "completed_llm_scopes": 1,
                    "tool_calls": 1,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=["web_search"],
            )

    def test_validate_trace_accepts_multiple_required_tool_names(self) -> None:
        events = []
        for name in ("read_file", "web_search", "write_file"):
            events.extend(
                [
                    {
                        "kind": "scope",
                        "category": "tool",
                        "scope_category": "start",
                        "uuid": name,
                        "name": name,
                    },
                    {
                        "kind": "scope",
                        "category": "tool",
                        "scope_category": "end",
                        "uuid": name,
                        "metadata": {"otel.status_code": "OK"},
                    },
                ]
            )

        summarize_atof.validate_trace_requirements(
            events,
            {
                "completed_llm_scopes": 1,
                "tool_calls": 3,
                "tool_errors": 0,
            },
            require_llm=True,
            require_tool=True,
            require_no_tool_errors=True,
            required_tool_command=None,
            required_tool_names=["read_file", "web_search", "write_file"],
        )

    def test_validate_trace_rejects_required_tool_without_matching_end(self) -> None:
        events = [
            {
                "kind": "scope",
                "category": "tool",
                "scope_category": "start",
                "uuid": "web-search",
                "name": "web_search",
            }
        ]

        with self.assertRaisesRegex(ValueError, "successful tool named 'web_search'"):
            summarize_atof.validate_trace_requirements(
                events,
                {
                    "completed_llm_scopes": 1,
                    "tool_calls": 1,
                    "tool_errors": 0,
                },
                require_llm=True,
                require_tool=True,
                require_no_tool_errors=True,
                required_tool_command=None,
                required_tool_names=["web_search"],
            )
