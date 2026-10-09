# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_harbor_eval import ROOT, check_job_result, main


class RunHarborEvalTest(unittest.TestCase):
    def invoke(self, run, split: str, arm: str) -> int:
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as raw:
            suite = Path(raw) / "suite.json"
            suite.write_text(
                json.dumps(
                    {
                        "cases": [
                            {"id": "dev-1", "case_kind": "development"},
                            {"id": "hold-1", "case_kind": "held_out"},
                        ]
                    }
                )
            )
            argv = [
                "run_harbor_eval.py",
                "--arm",
                arm,
                "--split",
                split,
                "--suite",
                str(suite),
                "--harbor",
                "/tmp/harbor",
            ]
            with patch.object(sys, "argv", argv):
                return main()

    @patch("scripts.run_harbor_eval.subprocess.run")
    @patch("scripts.run_harbor_eval.check_job_result", return_value=0)
    def test_environment_model_and_endpoint_reach_harbor(self, check, run) -> None:
        with patch.dict(os.environ, {
            "MODEL_SLUG": "my-custom-nemotron",
            "MODEL_BASE_URL": "https://models.example.test/v1",
        }):
            self.assertEqual(self.invoke(run, "development", "baseline"), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-m") + 1], "my-custom-nemotron")
        self.assertIn("provider_base_url=https://models.example.test/v1", command)
        self.assertTrue(any(str(item).startswith("openshell_provider=hermes-model-") for item in command))

    @patch("scripts.run_harbor_eval.subprocess.run")
    @patch("scripts.run_harbor_eval.check_job_result", return_value=0)
    def test_custom_agent_is_importable_from_clean_shell(self, check, run) -> None:
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as raw:
            suite = Path(raw) / "suite.json"
            suite.write_text(json.dumps({"cases": [{"id": "dev-1", "case_kind": "development"}]}))
            argv = [
                "run_harbor_eval.py", "--arm", "candidate", "--split", "development",
                "--suite", str(suite), "--harbor", "/tmp/harbor",
                "--provider-base-url", "https://inference.example.test/v1",
            ]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"PYTHONPATH": "prior"}):
                self.assertEqual(main(), 0)

        _, kwargs = run.call_args
        self.assertEqual(kwargs["cwd"], Path(ROOT))
        self.assertEqual(kwargs["env"]["PYTHONPATH"], f"{ROOT}{os.pathsep}prior")
        command = run.call_args.args[0]
        self.assertIn(
            "harbor_agents.openshell_hermes:OpenShellHermesFlywheel", command
        )
        self.assertIn("openshell_image=hermes-flywheel-openshell:0.3", command)
        self.assertEqual(command[command.index("--agent-timeout-multiplier") + 1], "2.0")
        self.assertIn(
            "provider_base_url=https://inference.example.test/v1", command
        )
        check.assert_called_once_with(ROOT / ".runs/harbor/candidate-development", 3)

    @patch("scripts.run_harbor_eval.subprocess.run")
    @patch("scripts.run_harbor_eval.check_job_result", return_value=0)
    def test_direct_runtime_remains_available(self, check, run) -> None:
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as raw:
            suite = Path(raw) / "suite.json"
            suite.write_text(json.dumps({"cases": [{"id": "hold-1", "case_kind": "held_out"}]}))
            argv = ["run_harbor_eval.py", "--arm", "baseline", "--split", "held-out", "--runtime", "direct", "--suite", str(suite)]
            with patch.object(sys, "argv", argv):
                self.assertEqual(main(), 0)

        command = run.call_args.args[0]
        self.assertIn("harbor_agents.hermes_flywheel:HermesFlywheel", command)
        self.assertFalse(any(str(arg).startswith("openshell_image=") for arg in command))

    def test_recorded_job_requires_terminal_complete_exception_free_trials(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for finished, completed, errors, expected in (
                ("done", 6, 0, 0), ("done", 6, 1, 1),
                (None, 6, 0, 1), ("done", 5, 0, 1),
            ):
                with self.subTest(finished=finished, completed=completed, errors=errors):
                    (root / "result.json").write_text(json.dumps({
                        "finished_at": finished,
                        "stats": {"n_completed_trials": completed, "n_errored_trials": errors},
                    }))
                    self.assertEqual(check_job_result(root, 6), expected)

    def test_missing_recorded_result_is_not_success(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(check_job_result(Path(raw), 6), 1)

    @patch("scripts.run_harbor_eval.subprocess.run")
    def test_empty_split_does_not_run_every_task(self, run):
        with tempfile.TemporaryDirectory() as raw:
            suite = Path(raw) / "suite.json"
            suite.write_text(json.dumps({"cases": []}))
            argv = ["run_harbor_eval.py", "--arm", "baseline", "--split", "development",
                    "--suite", str(suite)]
            with patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
