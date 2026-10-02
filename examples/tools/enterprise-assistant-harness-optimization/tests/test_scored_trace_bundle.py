# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_scored_trace_bundle import validate


def records(attempts: int):
    for case in ("task-a", "task-b"):
        for attempt in range(attempts):
            yield {
                "id": f"{case}-{attempt}",
                "attributes": {"logical_case_id": case},
                "evaluator_results": {"harbor.reward": float(attempt % 2)},
            }


class ScoredTraceBundleTest(unittest.TestCase):
    def test_repeated_scored_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "traces.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in records(3)))
            self.assertEqual(validate(path), [])

    def test_insufficient_repetitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "traces.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in records(2)))
            errors = validate(path)
            self.assertTrue(any("same number of traces" in error for error in errors))

    def test_missing_reward_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "traces.jsonl"
            path.write_text(json.dumps({"id": "one", "attributes": {"logical_case_id": "task-a"}}) + "\n")
            errors = validate(path)
            self.assertTrue(any("binary harbor.reward" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
