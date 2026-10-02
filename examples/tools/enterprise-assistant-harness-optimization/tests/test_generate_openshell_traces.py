# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from scripts import generate_openshell_traces
except (ImportError, ModuleNotFoundError):  # OpenShell adapter requires Python 3.12.
    generate_openshell_traces = None

from scripts.production_workload import validate_matrix


def arguments(root: Path, *, retries: int) -> argparse.Namespace:
    matrix = root / "matrix.json"
    matrix.write_text(
        json.dumps({"scenarios": [{"id": "case-a", "prompt": "Find it."}]}),
        encoding="utf-8",
    )
    return argparse.Namespace(
        matrix=matrix,
        case=None,
        output=root / "output",
        attempts=1,
        concurrency=1,
        retries=retries,
        model="nvidia/test-model",
        openshell_bin="openshell",
        openshell_image="test-image",
        openshell_provider="test-provider",
        provider_base_url="",
    )


class RetryThenSucceedAgent:
    calls = 0

    def __init__(self, *, logs_dir: Path, **_: object) -> None:
        self.logs_dir = logs_dir
        self.session_id = ""

    async def _host_command(self, *_: object, **__: object) -> None:
        return None

    async def execute_openshell(self, _: str, artifact_dir: Path) -> None:
        type(self).calls += 1
        if type(self).calls == 1:
            raise RuntimeError("transient model timeout")
        relay = artifact_dir / "relay" / "atif"
        relay.mkdir(parents=True)
        (relay / "trajectory-test.json").write_text("{}\n", encoding="utf-8")


class AlwaysFailAgent(RetryThenSucceedAgent):
    async def execute_openshell(self, _: str, artifact_dir: Path) -> None:
        del artifact_dir
        raise RuntimeError("persistent provider failure")


@unittest.skipIf(generate_openshell_traces is None, "OpenShell runtime is unavailable")
class GenerateOpenShellTracesTest(unittest.IsolatedAsyncioTestCase):
    def test_matrix_requires_distinct_prompt_rows_and_bounded_size(self) -> None:
        matrix = {
            "scenarios": [
                {"id": f"task-{index}", "prompt": f"Request {index}", "behavior_family": "coverage"}
                for index in range(36)
            ]
        }
        validate_matrix(matrix)
        matrix["scenarios"][1]["prompt"] = matrix["scenarios"][0]["prompt"]
        with self.assertRaisesRegex(ValueError, "prompts must be distinct"):
            validate_matrix(matrix)

    async def test_retries_one_logical_run_without_cancelling_the_batch(self) -> None:
        RetryThenSucceedAgent.calls = 0
        with tempfile.TemporaryDirectory() as raw:
            args = arguments(Path(raw), retries=1)
            with patch.object(
                generate_openshell_traces,
                "OpenShellHermesFlywheel",
                RetryThenSucceedAgent,
            ):
                records, failures = await generate_openshell_traces.collect(args)

        self.assertEqual(failures, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["runtime_attempts"], 2)
        self.assertIn("retry-01", records[0]["relay_atif"][0])

    async def test_retains_exhausted_run_in_failure_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            args = arguments(Path(raw), retries=1)
            with patch.object(
                generate_openshell_traces,
                "OpenShellHermesFlywheel",
                AlwaysFailAgent,
            ):
                records, failures = await generate_openshell_traces.collect(args)

        self.assertEqual(records, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["runtime_attempts"], 2)
        self.assertIn("persistent provider failure", failures[0]["errors"][0])


if __name__ == "__main__":
    unittest.main()
