# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_task_products import task_digest, validate


class TaskProductsTest(unittest.TestCase):
    def make_product(self, root: Path) -> Path:
        task = root / "evals/harbor-tasks-v3/demo-task"
        (task / "tests").mkdir(parents=True)
        (task / "environment").mkdir()
        (task / "instruction.md").write_text("Prepare a draft")
        (task / "tests/expected.json").write_text('{"outbox_count": 0}')
        (root / "fixtures").mkdir()
        (root / "fixtures/world-v2.json").write_text('{}')
        (task / "environment/world.json").write_text('{}')
        for parent in (task / "environment/pa_style_mock_mcp", root / "src/pa_style_mock_mcp"):
            parent.mkdir(parents=True)
            for name in ("tools.py", "world.py"):
                (parent / name).write_text("# shared deterministic implementation\n")
        (root / "evals/flywheel-eval-set-v3.json").write_text(json.dumps({"cases": [{
            "id": "demo-task", "input": "Prepare a draft", "expectations": {"outbox_count": 0},
            "provenance": {"harbor_task_ref": "evals/harbor-tasks-v3/demo-task"},
        }]}))
        proof_dir = root / "evals/task-proofs/demo-task"
        proof_dir.mkdir(parents=True)
        digest = task_digest(task)
        reproduction = {"task_tree_sha256": digest}
        (proof_dir / "reproducibility.json").write_text(json.dumps(reproduction))
        (proof_dir / "result.json").write_text(json.dumps({
            "task_id": "demo-task", "reproducibility": reproduction,
            "environment": {"review_status": "unreviewed"},
            "technical_validation": {
                "task_tree_sha256": digest, "passed": True,
                "verifier_environment_mode": "separate", "check_evidence": "per_check",
                "runs": {arm: [{"reward": reward, "exception_present": False}] * count
                         for arm, count, reward in (("nop", 2, 0), ("oracle", 2, 1), ("negative", 1, 0))},
            },
        }))
        return task

    def test_integrity_does_not_claim_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_product(root)
            self.assertEqual(validate(root, require_review=False), [])
            self.assertTrue(any("human task review" in error for error in validate(root)))

    def test_content_and_executable_bit_drift_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self.make_product(root)
            task.joinpath("instruction.md").chmod(0o755)
            self.assertTrue(any("task tree differs" in error for error in validate(root, require_review=False)))
            task.joinpath("instruction.md").chmod(0o644)
            task.joinpath("instruction.md").write_text("Send a message")
            self.assertTrue(any("instruction differs" in error for error in validate(root, require_review=False)))

    def test_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self.make_product(root)
            task.joinpath("link").symlink_to(task / "instruction.md")
            with self.assertRaises(ValueError):
                task_digest(task)

    def test_host_dispatcher_drift_is_rejected_without_editing_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_product(root)
            root.joinpath("src/pa_style_mock_mcp/tools.py").write_text("# easier mock behavior\n")
            self.assertTrue(any("host MCP tools.py differs" in error
                                for error in validate(root, require_review=False)))

    def test_custom_collection_and_manifest_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self.make_product(root)
            collection = root / ".runs/authored/tasks"
            collection.mkdir(parents=True)
            task.rename(collection / "demo-task")
            proofs = root / ".runs/authored/proofs"
            root.joinpath("evals/task-proofs").rename(proofs)
            suite = json.loads(root.joinpath("evals/flywheel-eval-set-v3.json").read_text())
            suite["cases"][0]["provenance"]["harbor_task_ref"] = ".runs/authored/tasks/demo-task"
            manifest = root / ".runs/authored/suite.json"
            manifest.write_text(json.dumps(suite))
            self.assertEqual(validate(root, require_review=False, suite_path=manifest,
                                      tasks_dir=collection, proofs_dir=proofs), [])
            suite["cases"][0]["provenance"]["harbor_task_ref"] = "some-other-collection/demo-task"
            manifest.write_text(json.dumps(suite))
            self.assertTrue(any("selected task differs" in error for error in
                                validate(root, require_review=False, suite_path=manifest,
                                         tasks_dir=collection, proofs_dir=proofs)))


if __name__ == "__main__":
    unittest.main()
