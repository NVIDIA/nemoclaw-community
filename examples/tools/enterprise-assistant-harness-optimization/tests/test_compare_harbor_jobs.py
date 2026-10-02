# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from scripts.compare_harbor_jobs import compare, wilson_interval


def write_job(root: Path, name: str, outcomes: dict[str, list[int]]) -> Path:
    job = root / name
    for task_id, rewards in outcomes.items():
        for attempt, reward in enumerate(rewards, start=1):
            trial = job / f"{task_id}__{attempt}"
            (trial / "verifier").mkdir(parents=True)
            (trial / "verifier/report.json").write_text(
                json.dumps({"tool_calls": [{"name": "chat.search"}], "failures": []})
            )
            (trial / "result.json").write_text(
                json.dumps(
                    {
                        "task_name": f"hermes-flywheel/{task_id}",
                        "trial_name": f"{task_id}__{attempt}",
                        "verifier_result": {"rewards": {"reward": reward}},
                    }
                )
            )
    return job


class CompareHarborJobsTest(unittest.TestCase):
    def test_reports_dynamic_denominators_and_all_four_arm_split_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            suite = root / "suite.json"
            suite.write_text(
                json.dumps(
                    {
                        "cases": [
                            {"id": "dev-a", "case_kind": "development"},
                            {"id": "dev-b", "case_kind": "development"},
                            {"id": "hold-a", "case_kind": "held_out"},
                        ]
                    }
                )
            )
            baseline_dev = write_job(root, "bd", {"dev-a": [0, 0, 0], "dev-b": [0, 1, 0]})
            candidate_dev = write_job(root, "cd", {"dev-a": [1, 1, 0], "dev-b": [1, 1, 1]})
            baseline_hold = write_job(root, "bh", {"hold-a": [0, 0, 0]})
            candidate_hold = write_job(root, "ch", {"hold-a": [1, 1, 0]})
            report = compare(
                suite,
                baseline_development=baseline_dev,
                candidate_development=candidate_dev,
                baseline_held_out=baseline_hold,
                candidate_held_out=candidate_hold,
                attempts=3,
            )
        self.assertEqual(report["development"]["baseline"]["trials"], 6)
        self.assertEqual(report["development"]["candidate"]["passed"], 5)
        self.assertTrue(report["development"]["candidate_improved"])
        self.assertTrue(report["held_out"]["candidate_improved"])
        self.assertEqual(report["development"]["regressed_tasks"], [])
        self.assertEqual(len(report["held_out"]["baseline"]["wilson_95"]), 2)

    def test_wilson_interval_handles_empty_and_perfect_samples(self) -> None:
        self.assertIsNone(wilson_interval(0, 0))
        lower, upper = wilson_interval(3, 3)
        self.assertLess(lower, 1.0)
        self.assertEqual(upper, 1.0)

    def test_aggregate_improvement_does_not_hide_task_regression(self) -> None:
        from scripts.compare_harbor_jobs import compare_split
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = write_job(root, "baseline", {"a": [1, 0, 0], "b": [0, 0, 0]})
            candidate = write_job(root, "candidate", {"a": [0, 0, 0], "b": [1, 1, 1]})
            report = compare_split(baseline, candidate, {"a", "b"}, 3)
            self.assertTrue(report["candidate_improved"])
            self.assertEqual(report["regressed_tasks"], ["a"])


if __name__ == "__main__":
    unittest.main()
