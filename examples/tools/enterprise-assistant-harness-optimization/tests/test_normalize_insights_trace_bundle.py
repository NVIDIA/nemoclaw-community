# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import unittest

from scripts.normalize_insights_trace_bundle import _source_prompt, convert


class NormalizeInsightsTraceBundleTest(unittest.TestCase):
    def test_reads_atof_prompt_without_runtime_context_fallback(self) -> None:
        self.assertEqual(_source_prompt({"prompt": "Original request"}), "Original request")

    def test_prefers_canonical_task_text_when_present(self) -> None:
        self.assertEqual(
            _source_prompt({"task_text": "Canonical request", "prompt": "Other"}),
            "Canonical request",
        )

    def test_preserves_fixture_call_and_harbor_reward(self) -> None:
        trace = {
            "id": "scored-trace",
            "attributes": {"task_text": "Prepare a message", "final_answer": "Prepared"},
            "evaluator_results": {"harbor.reward": 0.0},
            "root_spans": [{
                "kind": "TOOL", "tool_name": "actions.prepare_message",
                "input": {"recipient": "Maya Chen", "body": "Review requested"},
                "output": {"ok": True},
            }],
        }
        atif = convert(trace, collection="development", ordinal=1)
        self.assertEqual(atif["steps"][0]["message"], "Prepare a message")
        call = atif["steps"][1]["tool_calls"][0]
        self.assertEqual(call["arguments"], trace["root_spans"][0]["input"])
        self.assertEqual(atif["extra"]["evaluator_results"], {"harbor.reward": 0.0})
        self.assertTrue(atif["extra"]["tool_catalog"]["actions.prepare_message"])

    def test_redacts_non_fixture_payload_without_losing_call_identity(self) -> None:
        atif = convert({
            "id": "native-helper",
            "attributes": {"prompt": "Inspect a result"},
            "root_spans": [{"kind": "TOOL", "tool_name": "terminal",
                            "input": {"command": "private command"},
                            "output": "private output"}],
        }, collection="production", ordinal=1)
        call = atif["steps"][1]["tool_calls"][0]
        self.assertEqual(call["function_name"], "terminal")
        self.assertIn("redacted", call["arguments"])
        self.assertEqual(atif["extra"]["tool_catalog"]["terminal"], {})

    def test_preserves_recorded_usage_and_model_without_inventing_zero_totals(self):
        trace = {"id": "measured", "attributes": {
            "task_text": "Prepare a draft", "agent": {"model_name": "recorded-model"},
            "final_metrics": {"total_prompt_tokens": 123, "total_completion_tokens": 45},
        }, "root_spans": []}
        atif = convert(trace, collection="development", ordinal=1)
        self.assertEqual(atif["agent"]["model_name"], "recorded-model")
        self.assertEqual(atif["final_metrics"]["total_prompt_tokens"], 123)
        self.assertEqual(atif["final_metrics"]["total_completion_tokens"], 45)
        self.assertEqual(atif["final_metrics"]["total_steps"], len(atif["steps"]))

    def test_marks_missing_usage_unknown_instead_of_reporting_zero(self):
        atif = convert({"id": "unknown", "attributes": {"agent": None}, "root_spans": []},
                       collection="development", ordinal=1)
        self.assertNotIn("total_prompt_tokens", atif["final_metrics"])
        self.assertNotIn("total_completion_tokens", atif["final_metrics"])
        self.assertTrue(atif["extra"]["normalization"]["uncertainties"])


if __name__ == "__main__":
    unittest.main()
