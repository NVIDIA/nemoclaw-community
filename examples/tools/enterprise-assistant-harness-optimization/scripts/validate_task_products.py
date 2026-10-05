#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Check published task bytes against Eval Author's declassified proof receipts.

The tree-digest framing follows labs-eval-author's trace_environment.py v1.4.0.
This checks integrity of retained evidence; it does not rerun Harbor controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def task_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("task must be a regular directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"unsupported task entry: {path}")
        is_file = path.is_file()
        fields = (
            b"file" if is_file else b"directory",
            path.relative_to(root).as_posix().encode(),
            b"1" if is_file and stat.S_IMODE(path.stat().st_mode) & 0o111 else b"0",
        )
        for field in fields:
            digest.update(len(field).to_bytes(8, "big"))
            digest.update(field)
        payload = path.read_bytes() if is_file else b""
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def validate(root: Path, *, require_review: bool = True, suite_path: Path | None = None,
             tasks_dir: Path | None = None, proofs_dir: Path | None = None) -> list[str]:
    suite = json.loads((suite_path or root / "evals/flywheel-eval-set-v3.json").read_text())
    errors = []
    for case in suite["cases"]:
        task_id = case["id"]
        task = (tasks_dir / task_id) if tasks_dir else root / case["provenance"]["harbor_task_ref"]
        if task.resolve() != (root / case["provenance"]["harbor_task_ref"]).resolve():
            errors.append(f"{task_id}: selected task differs from manifest reference")
        proof_dir = (proofs_dir or root / "evals/task-proofs") / task_id
        receipt = json.loads((proof_dir / "result.json").read_text())
        reproduction = json.loads((proof_dir / "reproducibility.json").read_text())
        actual_hash = task_digest(task)
        proof = receipt["technical_validation"]
        if any(record.get("task_tree_sha256") != actual_hash for record in (proof, reproduction, receipt["reproducibility"])):
            errors.append(f"{task_id}: task tree differs from proven export")
        if receipt.get("task_id") != task_id or proof.get("passed") is not True:
            errors.append(f"{task_id}: missing passing task proof")
        if proof.get("verifier_environment_mode") != "separate" or proof.get("check_evidence") != "per_check":
            errors.append(f"{task_id}: proof lacks separate per-check verification")
        for arm, count, reward in (("nop", 2, 0), ("oracle", 2, 1), ("negative", 1, 0)):
            runs = proof.get("runs", {}).get(arm, [])
            if len(runs) < count or any(run.get("reward") != reward or run.get("exception_present") is not False for run in runs):
                errors.append(f"{task_id}: invalid {arm} controls")
        review = receipt["environment"].get("review_status")
        if review not in ("human_reviewed", "unreviewed") or (require_review and review != "human_reviewed"):
            errors.append(f"{task_id}: human task review remains unproven")
        if task.joinpath("instruction.md").read_text().strip() != case["input"].strip():
            errors.append(f"{task_id}: instruction differs from frozen suite")
        expected = json.loads(task.joinpath("tests/expected.json").read_text())
        if any(expected.get(key) != value for key, value in case["expectations"].items()):
            errors.append(f"{task_id}: verifier differs from frozen expectations")
        if task.joinpath("environment/world.json").read_bytes() != root.joinpath("fixtures/world-v2.json").read_bytes():
            errors.append(f"{task_id}: task fixture differs from host MCP fixture")
        for name in ("tools.py", "world.py"):
            packaged = task / "environment/pa_style_mock_mcp" / name
            host = root / "src/pa_style_mock_mcp" / name
            if packaged.read_bytes() != host.read_bytes():
                errors.append(f"{task_id}: host MCP {name} differs from the proven implementation")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--tasks-dir", type=Path)
    parser.add_argument("--proofs-dir", type=Path)
    args = parser.parse_args()
    errors = validate(ROOT, require_review=not args.allow_unreviewed, suite_path=args.suite,
                      tasks_dir=args.tasks_dir, proofs_dir=args.proofs_dir)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Published task hashes and technical proof receipts match.")
    if args.allow_unreviewed:
        print("Technical integrity only: human task review is not established by this check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
