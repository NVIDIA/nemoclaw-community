# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import unittest

from pa_style_mock_mcp.insights import (
    apply_runner_outcomes,
    atif_to_insights_trace,
    atof_events_to_insights_traces,
)


class InsightsAdapterTests(unittest.TestCase):
    def test_maps_recorded_call_result_and_catalog_without_inventing_error(self) -> None:
        atif = {
            "schema_version": "ATIF-v1.7",
            "trajectory_id": "trace-1",
            "session_id": "session-1",
            "agent": {"name": "Hermes"},
            "steps": [
                {
                    "step_id": 1,
                    "source": "user",
                    "message": "Find the packet",
                    "extra": {
                        "llm_request": {
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "files_search",
                                        "parameters": {"type": "object"},
                                    },
                                }
                            ]
                        }
                    },
                },
                {
                    "step_id": 2,
                    "source": "agent",
                    "message": "",
                    "timestamp": "2026-09-11T12:00:00+00:00",
                    "tool_calls": [
                        {
                            "tool_call_id": "call-1",
                            "function_name": "files_search",
                            "arguments": {"query": "packet"},
                        }
                    ],
                    "observation": {
                        "results": [
                            {"source_call_id": "call-1", "content": '{"ok":true}'}
                        ]
                    },
                },
                {"step_id": 3, "source": "agent", "message": "Found it."},
            ],
        }

        trace = atif_to_insights_trace(atif, logical_case_id="packet-case")

        self.assertEqual(trace["id"], "trace-1")
        self.assertEqual(trace["attributes"]["logical_case_id"], "packet-case")
        self.assertEqual(trace["attributes"]["task_text"], "Find the packet")
        self.assertEqual(trace["evaluator_results"], {})
        self.assertEqual(trace["attributes"]["final_answer"], "Found it.")
        self.assertEqual(trace["attributes"]["tool_catalog"], {"files_search": {"type": "object"}})
        span = trace["root_spans"][0]
        self.assertEqual(span["tool_call"]["result_count"], 1)
        self.assertEqual(span["tool_call"]["prior_user_text"], "Find the packet")
        self.assertEqual(span["output"], '{"ok":true}')
        self.assertNotIn("error", span)

    def test_preserves_missing_result_as_result_count_zero(self) -> None:
        atif = {
            "schema_version": "ATIF-v1.7",
            "session_id": "session-1",
            "steps": [
                {
                    "source": "agent",
                    "tool_calls": [
                        {"tool_call_id": "call-1", "function_name": "search", "arguments": {}}
                    ],
                }
            ],
        }

        span = atif_to_insights_trace(atif)["root_spans"][0]

        self.assertEqual(span["tool_call"]["result_count"], 0)
        self.assertNotIn("output", span)

    def test_unwraps_broker_calls_and_recovers_discovered_schema(self) -> None:
        atif = {
            "schema_version": "ATIF-v1.7",
            "session_id": "session-broker",
            "steps": [
                {
                    "source": "agent",
                    "tool_calls": [
                        {
                            "tool_call_id": "discover",
                            "function_name": "tool_describe",
                            "arguments": {"names": ["mcp__enterprise__chat_search"]},
                        }
                    ],
                    "observation": {
                        "results": [
                            {
                                "source_call_id": "discover",
                                "content": '{"tools":{"mcp__enterprise__chat_search":'
                                '{"parameters":{"type":"object","required":["query"]}}}}',
                            }
                        ]
                    },
                },
                {
                    "source": "agent",
                    "tool_calls": [
                        {
                            "tool_call_id": "invoke",
                            "function_name": "tool_call",
                            "arguments": {
                                "calls": [
                                    {
                                        "name": "mcp__enterprise__chat_search",
                                        "arguments": {"query": "launch"},
                                    }
                                ]
                            },
                        }
                    ],
                    "observation": {
                        "results": [
                            {"source_call_id": "invoke", "content": '{"result":"ok"}'}
                        ]
                    },
                },
            ],
        }

        trace = atif_to_insights_trace(atif)

        invoked = trace["root_spans"][1]
        self.assertEqual(invoked["tool_name"], "mcp__enterprise__chat_search")
        self.assertEqual(invoked["input"], {"query": "launch"})
        self.assertEqual(invoked["attributes"]["broker_tool_name"], "tool_call")
        self.assertEqual(
            trace["attributes"]["tool_catalog"]["mcp__enterprise__chat_search"],
            {"type": "object", "required": ["query"]},
        )

    def test_groups_completed_atof_turn_and_joins_tool_scope(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:00+00:00"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:01+00:00", "data": {"content": {"messages": [{"role": "user", "content": "Find it"}], "tools": [{"function": {"name": "search", "parameters": {"type": "object"}}}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:02+00:00", "data": {"model": "nemotron", "usage": {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 4}, "completion_tokens": 3}, "choices": [{"message": {"content": "Found it"}}]}},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "search", "uuid": "tool", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:02+00:00", "data": {"query": "it"}, "metadata": {"tool_call_id": "call-1"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "search", "uuid": "tool", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:03+00:00", "data": {"ok": True}, "metadata": {"tool_call_id": "call-1", "otel.status_code": "OK"}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:04+00:00", "data": {"outcome": "success"}},
        ]

        trace = atof_events_to_insights_traces(
            events,
            prompt_case_ids={"Find it": "find"},
            case_required_signals={"find": ["chat.search"]},
        )[0]

        self.assertEqual(trace["attributes"]["logical_case_id"], "find")
        self.assertEqual(trace["attributes"]["observed_verdict"], "missing required enterprise evidence")
        self.assertEqual(trace["attributes"]["metrics"]["required_signal_coverage"], 0.0)
        self.assertEqual(trace["attributes"]["final_answer"], "Found it")
        self.assertEqual(trace["aggregate"]["latency_ms"], 4000)
        self.assertEqual(trace["aggregate"]["token_counts"], {"input_tokens": 6, "cached_input_tokens": 4, "output_tokens": 3})
        self.assertEqual(trace["root_spans"][0]["tool_call"]["result_id"], "call-1")
        self.assertTrue(trace["attributes"]["infrastructure_valid"])
        self.assertEqual(trace["attributes"]["provider_errors"], [])

    def test_marks_turn_with_recorded_provider_error_as_invalid(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": None, "metadata": {"error.type": "rate_limit", "exception.type": "RateLimitError"}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "failed"}},
        ]

        trace = atof_events_to_insights_traces(events)[0]

        self.assertFalse(trace["attributes"]["infrastructure_valid"])
        self.assertEqual(
            trace["attributes"]["provider_errors"],
            [{"error_type": "rate_limit", "exception_type": "RateLimitError"}],
        )

    def test_marks_mcp_transport_failure_as_infrastructure_invalid(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "mcp__enterprise_world__chat_search", "uuid": "tool", "parent_uuid": "turn", "metadata": {"tool_call_id": "call"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "mcp__enterprise_world__chat_search", "uuid": "tool", "parent_uuid": "turn", "data": {"error": "MCP call failed: MCPError: Connection closed"}, "metadata": {"tool_call_id": "call"}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "success"}},
        ]

        trace = atof_events_to_insights_traces(events)[0]

        self.assertFalse(trace["attributes"]["infrastructure_valid"])
        self.assertEqual(
            trace["attributes"]["infrastructure_errors"][0]["marker"],
            "mcp call failed: mcperror: connection closed",
        )

    def test_recovered_provider_error_remains_valid_and_recorded(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "failed", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "failed", "parent_uuid": "turn", "data": None, "metadata": {"error.type": "rate_limit"}},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "ok", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "ok", "parent_uuid": "turn", "data": {"choices": [{"message": {"content": "done"}}]}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "success"}},
        ]

        trace = atof_events_to_insights_traces(events)[0]

        self.assertTrue(trace["attributes"]["infrastructure_valid"])
        self.assertEqual(len(trace["attributes"]["provider_errors"]), 1)

    def test_tolerates_llm_scope_with_null_payload(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:00+00:00"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": None},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": None},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:01+00:00", "data": None},
        ]

        trace = atof_events_to_insights_traces(events)[0]

        self.assertEqual(trace["attributes"]["final_answer"], "")
        self.assertEqual(trace["root_spans"], [])

    def test_matches_matrix_prompt_before_runtime_context(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:00+00:00"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {"content": {"messages": [{"role": "user", "content": "Find it\n\nHermes runtime context:\n- sandbox"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:01+00:00", "data": {}},
        ]

        trace = atof_events_to_insights_traces(events, prompt_case_ids={"Find it": "find"})[0]

        self.assertEqual(trace["attributes"]["logical_case_id"], "find")
        self.assertEqual(trace["attributes"]["prompt"], "Find it")
        self.assertNotIn("runtime context", trace["attributes"]["prompt"])

    def test_keeps_original_matrix_prompt_when_retry_adds_continuation(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "first", "parent_uuid": "turn", "data": {"content": {"messages": [{"role": "user", "content": "Find it\n\nHermes runtime context:\n- sandbox"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "first", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "retry", "parent_uuid": "turn", "data": {"content": {"messages": [{"role": "user", "content": "[System: Continue where you left off.]"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "retry", "parent_uuid": "turn", "data": {"choices": [{"message": {"content": "done"}}]}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "success"}},
        ]

        trace = atof_events_to_insights_traces(
            events, prompt_case_ids={"Find it": "find"}
        )[0]

        self.assertEqual(trace["attributes"]["logical_case_id"], "find")
        self.assertEqual(trace["attributes"]["prompt"], "Find it")

    def test_recognizes_tool_prefix_created_by_walkthrough_server_name(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {"content": {"messages": [{"role": "user", "content": "Find it"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "data": {}},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "mcp__enterprise_world__chat_search", "uuid": "tool", "parent_uuid": "turn", "metadata": {"tool_call_id": "call"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "mcp__enterprise_world__chat_search", "uuid": "tool", "parent_uuid": "turn", "data": {"ok": True}},
            {"kind": "scope", "scope_category": "end", "category": "function", "name": "hermes.turn", "uuid": "turn", "data": {"outcome": "success"}},
        ]

        trace = atof_events_to_insights_traces(
            events,
            prompt_case_ids={"Find it": "find"},
            case_required_signals={"find": ["chat.search"]},
        )[0]

        self.assertEqual(trace["attributes"]["metrics"]["required_signal_coverage"], 1.0)
        self.assertNotIn("observed_verdict", trace["attributes"])

    def test_includes_bounded_incomplete_turn_as_agent_failure(self) -> None:
        events = [
            {"kind": "scope", "scope_category": "start", "category": "function", "name": "hermes.turn", "uuid": "turn", "timestamp": "2026-09-11T12:00:00+00:00"},
            {"kind": "scope", "scope_category": "start", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:01+00:00", "data": {"content": {"messages": [{"role": "user", "content": "Find it"}]}}},
            {"kind": "scope", "scope_category": "end", "category": "llm", "name": "openai.chat_completions", "uuid": "llm", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:02+00:00", "data": {"choices": [{"message": {"content": "Still searching"}}]}},
            {"kind": "scope", "scope_category": "start", "category": "tool", "name": "terminal", "uuid": "tool", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:03+00:00", "metadata": {"tool_call_id": "call"}},
            {"kind": "scope", "scope_category": "end", "category": "tool", "name": "terminal", "uuid": "tool", "parent_uuid": "turn", "timestamp": "2026-09-11T12:00:04+00:00", "data": {"outcome": "success"}},
        ]

        self.assertEqual(atof_events_to_insights_traces(events), [])
        trace = atof_events_to_insights_traces(
            events,
            prompt_case_ids={"Find it": "find"},
            include_incomplete=True,
        )[0]

        self.assertEqual(trace["attributes"]["logical_case_id"], "find")
        self.assertEqual(trace["attributes"]["turn_outcome"], "failed")
        self.assertEqual(trace["attributes"]["termination_reason"], "incomplete_relay_turn")
        self.assertTrue(trace["attributes"]["infrastructure_valid"])
        self.assertEqual(trace["aggregate"]["latency_ms"], 4000)
        self.assertEqual(trace["root_spans"][0]["tool_name"], "terminal")

    def test_runner_timeout_overrides_late_relay_success(self) -> None:
        traces = [
            {
                "id": "turn",
                "root_spans": [
                    {"tool_name": "before", "start_time": "2026-09-11T12:00:01+00:00"},
                    {"tool_name": "after", "start_time": "2026-09-11T12:05:01+00:00"},
                ],
                "aggregate": {"latency_ms": 360000},
                "attributes": {
                    "logical_case_id": "case",
                    "turn_outcome": "success",
                    "final_answer": "late answer",
                    "infrastructure_valid": True,
                    "started_at": "2026-09-11T12:00:00+00:00",
                },
            }
        ]
        records = [
            {
                "case_id": "case",
                "trial": 1,
                "attempt": 1,
                "returncode": 124,
                "completed_at": "2026-09-11T12:05:00+00:00",
                "workspace": "/sandbox/eval-workspaces/case",
            }
        ]

        apply_runner_outcomes(traces, records)

        self.assertEqual(traces[0]["attributes"]["turn_outcome"], "failed")
        self.assertEqual(traces[0]["attributes"]["termination_reason"], "runner_timeout")
        self.assertEqual(traces[0]["attributes"]["final_answer"], "")
        self.assertEqual([span["tool_name"] for span in traces[0]["root_spans"]], ["before"])
        self.assertEqual(traces[0]["aggregate"]["latency_ms"], 300000)

    def test_runner_timeout_does_not_erase_recorded_infrastructure_failure(self) -> None:
        traces = [
            {
                "id": "turn",
                "root_spans": [],
                "aggregate": {},
                "attributes": {
                    "logical_case_id": "case",
                    "turn_outcome": "failed",
                    "infrastructure_valid": False,
                },
            }
        ]
        records = [
            {
                "case_id": "case",
                "trial": 1,
                "attempt": 1,
                "returncode": 124,
                "completed_at": "2026-09-11T12:05:00+00:00",
                "workspace": "/sandbox/eval-workspaces/case",
            }
        ]

        apply_runner_outcomes(traces, records)

        self.assertFalse(traces[0]["attributes"]["infrastructure_valid"])

    def test_runner_infrastructure_failure_overrides_exit_zero(self) -> None:
        traces = [
            {
                "id": "turn",
                "root_spans": [],
                "aggregate": {},
                "attributes": {
                    "logical_case_id": "case",
                    "turn_outcome": "success",
                    "infrastructure_valid": True,
                },
            }
        ]
        records = [
            {
                "case_id": "case",
                "trial": 1,
                "attempt": 1,
                "returncode": 0,
                "completed_at": "2026-09-11T12:00:00+00:00",
                "workspace": "/sandbox/eval-workspaces/case",
                "infrastructure_error": "MCP postflight discovery failed",
            }
        ]

        apply_runner_outcomes(traces, records)

        self.assertFalse(traces[0]["attributes"]["infrastructure_valid"])
        self.assertEqual(
            traces[0]["attributes"]["termination_reason"],
            "runner_infrastructure_failure",
        )


if __name__ == "__main__":
    unittest.main()
