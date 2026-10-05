# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from scripts.compare_harbor_jobs import compare, validate_run_identity, wilson_interval


def write_job(root: Path, name: str, outcomes: dict[str, list[int]], *, arm: str = "baseline") -> Path:
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
                        "task_checksum": f"checksum-{task_id}",
                        "config": {
                            "agent": {"model_name": "nvidia/test-model", "kwargs": {"arm": arm}},
                            "agent_timeout_multiplier": 2.0,
                        },
                        "verifier_result": {"rewards": {"reward": reward}},
                    }
                )
            )
            artifacts = trial / "artifacts/logs/artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "runtime-fingerprint.json").write_text(json.dumps({
                "schema": "hermes-runtime-fingerprint-v1",
                "arm": arm, "requested_model": "nvidia/test-model",
                "provider": "test-provider", "provider_base_url": "https://model.example/v1",
                "openshell_image": "test-image",
                "harness_config_sha256": "a" * 64,
                "profile_sha256": ("b" if arm == "baseline" else "c") * 64,
                "policy_sha256": "d" * 64, "fixture_sha256": "e" * 64,
                "mcp_implementation_sha256": {"tools.py": "f" * 64, "world.py": "0" * 64},
            }))
    return job


class CompareHarborJobsTest(unittest.TestCase):
    def test_saved_experiment_has_matching_run_identities(self) -> None:
        root = Path(__file__).parents[1]
        runs = []
        for arm in ("baseline", "candidate"):
            for split in ("development", "held-out"):
                summary = json.loads((root / f"results/{arm}-{split}-summary.json").read_text())
                tasks = {}
                for trial in summary["trials"]:
                    task_id = trial["task"].rsplit("/", 1)[-1]
                    tasks.setdefault(task_id, []).append(trial)
                runs.append((arm, tasks))
        validate_run_identity(runs)

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
            candidate_dev = write_job(root, "cd", {"dev-a": [1, 1, 0], "dev-b": [1, 1, 1]}, arm="candidate")
            baseline_hold = write_job(root, "bh", {"hold-a": [0, 0, 0]})
            candidate_hold = write_job(root, "ch", {"hold-a": [1, 1, 0]}, arm="candidate")
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
            candidate = write_job(root, "candidate", {"a": [0, 0, 0], "b": [1, 1, 1]}, arm="candidate")
            report = compare_split(baseline, candidate, {"a", "b"}, 3)
            self.assertTrue(report["candidate_improved"])
            self.assertEqual(report["regressed_tasks"], ["a"])

    def test_rejects_mismatched_or_missing_run_identity(self) -> None:
        from scripts.compare_harbor_jobs import compare_split

        changes = {
            "wrong arm": lambda result, fp: result["config"]["agent"]["kwargs"].update(arm="baseline"),
            "wrong fingerprint arm": lambda result, fp: fp.update(arm="baseline"),
            "inconsistent model": lambda result, fp: result["config"]["agent"].update(model_name="nvidia/other"),
            "different model": lambda result, fp: (
                result["config"]["agent"].update(model_name="nvidia/other"),
                fp.update(requested_model="nvidia/other")),
            "timeout budget": lambda result, fp: result["config"].update(agent_timeout_multiplier=3),
            "task checksum": lambda result, fp: result.update(task_checksum="different"),
            "missing task checksum": lambda result, fp: result.pop("task_checksum"),
            "missing model": lambda result, fp: result["config"]["agent"].pop("model_name"),
            "missing fingerprint": lambda result, fp: fp.clear(),
            "profile drift": lambda result, fp: fp.update(profile_sha256="1" * 64),
            "policy drift": lambda result, fp: fp.update(policy_sha256="1" * 64),
            "world drift": lambda result, fp: fp.update(fixture_sha256="1" * 64),
            "harness budget drift": lambda result, fp: fp.update(harness_config_sha256="1" * 64),
            "MCP drift": lambda result, fp: fp["mcp_implementation_sha256"].update({"tools.py": "1" * 64}),
        }
        for label, change in changes.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                baseline = write_job(root, "baseline", {"a": [0, 0, 0]})
                candidate = write_job(root, "candidate", {"a": [1, 1, 1]}, arm="candidate")
                trial = candidate / "a__1"
                result_path = trial / "result.json"
                fp_path = trial / "artifacts/logs/artifacts/runtime-fingerprint.json"
                result, fp = json.loads(result_path.read_text()), json.loads(fp_path.read_text())
                change(result, fp)
                result_path.write_text(json.dumps(result))
                fp_path.write_text(json.dumps(fp))
                with self.assertRaises(ValueError):
                    compare_split(baseline, candidate, {"a"}, 3)

    def test_rejects_settings_changed_between_development_and_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            suite = root / "suite.json"
            suite.write_text(json.dumps({"cases": [
                {"id": "dev", "case_kind": "development"},
                {"id": "hold", "case_kind": "held_out"},
            ]}))
            bd = write_job(root, "bd", {"dev": [0, 0, 0]})
            cd = write_job(root, "cd", {"dev": [1, 1, 1]}, arm="candidate")
            bh = write_job(root, "bh", {"hold": [0, 0, 0]})
            ch = write_job(root, "ch", {"hold": [1, 1, 1]}, arm="candidate")
            for job in (bh, ch):
                for result_path in job.glob("*/result.json"):
                    result = json.loads(result_path.read_text())
                    result["config"]["agent_timeout_multiplier"] = 3.0
                    result_path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "settings differ"):
                compare(suite, baseline_development=bd, candidate_development=cd,
                        baseline_held_out=bh, candidate_held_out=ch, attempts=3)

    def test_rejects_missing_runtime_fingerprint_file(self) -> None:
        from scripts.compare_harbor_jobs import compare_split

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = write_job(root, "baseline", {"a": [0, 0, 0]})
            candidate = write_job(root, "candidate", {"a": [1, 1, 1]}, arm="candidate")
            (candidate / "a__1/artifacts/logs/artifacts/runtime-fingerprint.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing runtime fingerprint"):
                compare_split(baseline, candidate, {"a"}, 3)


if __name__ == "__main__":
    unittest.main()
