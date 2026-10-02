# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import unittest

from scripts.validate_trace_derived_suite import validate


class TraceDerivedSuiteTest(unittest.TestCase):
    def suite(self):
        return {
            "suite_version": "3.0",
            "generation": {
                "method": "codex-with-nemo-eval-author",
                "selection_rationale": "Tasks represent distinct production insights and trace evidence.",
                "review_status": "human_reviewed",
                "source_corpus": "traces/world-v3/production/index.json",
                "source_trace_count": 42,
                "production_insights": "results/production-insights.yml",
                "split_frozen_before_candidate": True,
            },
            "cases": [
                {
                    "id": "coverage-task",
                    "case_kind": "development",
                    "behavior_family": "multi_source_coverage",
                    "input": "Find the launch blocker and review time.",
                    "expectations": {"required_tools": ["chat.search"]},
                    "relevant_experience": "A human reviewer describes why cross-source launch evidence matters.",
                    "provenance": {
                        "trace_ref": "traces/world-v3/production/trace-001.atif.json",
                        "insight_refs": ["INS-001"],
                        "harbor_task_ref": "evals/harbor-tasks-v3/coverage-task",
                    },
                },
                {
                    "id": "coverage-held-out",
                    "case_kind": "held_out",
                    "behavior_family": "multi_source_coverage",
                    "input": "Summarize the blocker and scheduled review.",
                    "expectations": {"required_tools": ["chat.search"]},
                    "relevant_experience": "A human reviewer describes why this wording is a fair held-out case.",
                    "provenance": {
                        "trace_ref": "traces/world-v3/production/trace-002.atif.json",
                        "insight_refs": ["INS-001"],
                        "held_out_from_case_ids": ["coverage-task"],
                        "harbor_task_ref": "evals/harbor-tasks-v3/coverage-held-out",
                    },
                },
            ],
        }

    def test_suite_uses_dynamic_case_counts_and_insight_provenance(self) -> None:
        self.assertEqual(validate(self.suite()), [])

    def test_source_trace_count_must_be_in_supported_range(self) -> None:
        suite = self.suite()
        suite["generation"]["source_trace_count"] = 12
        self.assertTrue(any("source_trace_count" in error for error in validate(suite)))

    def test_draft_runs_do_not_establish_human_review(self) -> None:
        suite = self.suite()
        suite["generation"]["review_status"] = "pending_human_review"
        self.assertTrue(any("human review" in error for error in validate(suite)))
        self.assertEqual(validate(suite, require_review=False), [])

    def test_unknown_review_status_is_never_accepted(self) -> None:
        suite = self.suite()
        suite["generation"]["review_status"] = "reviewed_by_model"
        self.assertTrue(validate(suite, require_review=False))

    def test_held_out_case_must_reference_development_behavior(self) -> None:
        suite = self.suite()
        suite["cases"][1]["provenance"]["held_out_from_case_ids"] = ["missing"]
        self.assertTrue(any("development behavior parent" in error for error in validate(suite)))

    def test_custom_task_collection_is_supported_but_unsafe_paths_are_not(self) -> None:
        suite = self.suite()
        for case in suite["cases"]:
            case["provenance"]["harbor_task_ref"] = f".runs/authored/tasks/{case['id']}"
        self.assertEqual(validate(suite), [])
        suite["cases"][0]["provenance"]["harbor_task_ref"] = "../coverage-task"
        self.assertTrue(any("Harbor task reference" in error for error in validate(suite)))


if __name__ == "__main__":
    unittest.main()
