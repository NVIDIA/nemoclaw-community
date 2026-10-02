#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compare baseline/candidate Harbor jobs on frozen development and holdout splits."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def load_trials(job_dir: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result_path in sorted(job_dir.glob("*/result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        task_id = str(result.get("task_name") or "").rsplit("/", 1)[-1]
        reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
        if not task_id or reward not in (0, 1, 0.0, 1.0):
            raise ValueError(f"invalid task or Harbor reward in {result_path}")
        report_path = result_path.parent / "verifier" / "report.json"
        report = (
            json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.is_file()
            else {}
        )
        grouped[task_id].append(
            {
                "trial": result.get("trial_name"),
                "reward": float(reward),
                "exception": result.get("exception_info"),
                "tool_calls": len(report.get("tool_calls", [])),
                "failures": report.get("failures", []),
            }
        )
    for trials in grouped.values():
        trials.sort(key=lambda item: str(item.get("trial") or ""))
    return dict(grouped)


def summarize_arm(trials: dict[str, list[dict[str, Any]]], attempts: int) -> dict[str, Any]:
    task_summaries = {}
    flat = []
    for task_id, task_trials in sorted(trials.items()):
        if len(task_trials) != attempts:
            raise ValueError(
                f"{task_id} has {len(task_trials)} attempts, expected exactly {attempts}"
            )
        rewards = [trial["reward"] for trial in task_trials]
        task_summaries[task_id] = {
            "passed": int(sum(rewards)),
            "trials": len(rewards),
            "pass_rate": sum(rewards) / len(rewards),
        }
        flat.extend(task_trials)
    passed = sum(trial["reward"] for trial in flat)
    total = len(flat)
    calls = [trial["tool_calls"] for trial in flat]
    return {
        "passed": int(passed),
        "trials": total,
        "pass_rate": passed / total if total else 0.0,
        "wilson_95": wilson_interval(int(passed), total),
        "exceptions": sum(bool(trial["exception"]) for trial in flat),
        "tool_calls": sum(calls),
        "mean_tool_calls": sum(calls) / len(calls) if calls else None,
        "per_task": task_summaries,
    }


def compare_split(
    baseline_job: Path,
    candidate_job: Path,
    expected_ids: set[str],
    attempts: int,
) -> dict[str, Any]:
    baseline = load_trials(baseline_job)
    candidate = load_trials(candidate_job)
    if set(baseline) != expected_ids:
        raise ValueError(f"baseline task IDs differ from frozen split: {sorted(set(baseline) ^ expected_ids)}")
    if set(candidate) != expected_ids:
        raise ValueError(f"candidate task IDs differ from frozen split: {sorted(set(candidate) ^ expected_ids)}")
    baseline_summary = summarize_arm(baseline, attempts)
    candidate_summary = summarize_arm(candidate, attempts)
    if any(len(candidate[key]) != len(baseline[key]) for key in expected_ids):
        raise ValueError("baseline/candidate task repetition counts differ")
    return {
        "tasks": len(expected_ids),
        "attempts_per_task_per_arm": attempts,
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "pass_rate_delta": candidate_summary["pass_rate"] - baseline_summary["pass_rate"],
        "candidate_improved": candidate_summary["pass_rate"] > baseline_summary["pass_rate"],
        "regressed_tasks": sorted(
            task_id for task_id in expected_ids
            if candidate_summary["per_task"][task_id]["passed"]
            < baseline_summary["per_task"][task_id]["passed"]
        ),
    }


def compare(
    suite_path: Path,
    *,
    baseline_development: Path,
    candidate_development: Path,
    baseline_held_out: Path,
    candidate_held_out: Path,
    attempts: int,
) -> dict[str, Any]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    dev_ids = {
        case["id"] for case in suite["cases"] if case.get("case_kind") == "development"
    }
    held_ids = {
        case["id"] for case in suite["cases"] if case.get("case_kind") == "held_out"
    }
    if not dev_ids or not held_ids:
        raise ValueError("frozen suite must contain development and held-out tasks")
    return {
        "schema": "hermes-harbor-ab-comparison-v3",
        "suite": str(suite_path),
        "attempts_per_task_per_arm": attempts,
        "development": compare_split(
            baseline_development, candidate_development, dev_ids, attempts
        ),
        "held_out": compare_split(
            baseline_held_out, candidate_held_out, held_ids, attempts
        ),
        "acceptance": {
            "candidate_improves_development": False,
            "candidate_improves_held_out": False,
            "both_splits_improve": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--baseline-development", type=Path, required=True)
    parser.add_argument("--candidate-development", type=Path, required=True)
    parser.add_argument("--baseline-held-out", type=Path, required=True)
    parser.add_argument("--candidate-held-out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.attempts < 3:
        parser.error("--attempts must be at least 3")
    report = compare(
        args.suite,
        baseline_development=args.baseline_development,
        candidate_development=args.candidate_development,
        baseline_held_out=args.baseline_held_out,
        candidate_held_out=args.candidate_held_out,
        attempts=args.attempts,
    )
    report["acceptance"].update(
        candidate_improves_development=report["development"]["candidate_improved"],
        candidate_improves_held_out=report["held_out"]["candidate_improved"],
        both_splits_improve=(
            report["development"]["candidate_improved"]
            and report["held_out"]["candidate_improved"]
        ),
        no_task_regressions=not (
            report["development"]["regressed_tasks"] or report["held_out"]["regressed_tasks"]
        ),
        no_runtime_exceptions=not any(
            report[split][arm]["exceptions"]
            for split in ("development", "held_out") for arm in ("baseline", "candidate")
        ),
    )
    report["acceptance"]["accepted"] = all(
        report["acceptance"][key]
        for key in ("both_splits_improve", "no_task_regressions", "no_runtime_exceptions")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["acceptance"]))
    return 0 if report["acceptance"]["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
