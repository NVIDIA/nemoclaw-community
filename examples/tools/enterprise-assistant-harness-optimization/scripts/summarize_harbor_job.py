#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Summarize authoritative Harbor rewards and harness artifacts for one job."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    trials = []
    runtime_records: list[dict[str, Any]] = []
    job_result_path = args.job_dir / "result.json"
    job_result = _load(job_result_path) if job_result_path.is_file() else {}
    for result_path in sorted(args.job_dir.glob("*/result.json")):
        result = _load(result_path)
        agent_info = result.get("agent_info")
        if isinstance(agent_info, dict) and agent_info not in runtime_records:
            runtime_records.append(agent_info)
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        reward = rewards.get("reward")
        report_path = result_path.parent / "verifier" / "report.json"
        report = _load(report_path) if report_path.exists() else {}
        artifact_root = result_path.parent / "artifacts" / "logs" / "artifacts"
        fingerprint_path = artifact_root / "runtime-fingerprint.json"
        relay_ids = set()
        for path in (artifact_root / "relay" / "atif").glob("*.json"):
            trajectory = _load(path)
            trace_id = trajectory.get("trajectory_id") or trajectory.get("session_id")
            if isinstance(trace_id, str) and trace_id:
                relay_ids.add(trace_id)
        trials.append(
            {
                "task": result.get("task_name"),
                "trial": result.get("trial_name"),
                "task_checksum": result.get("task_checksum"),
                "verifier_environment_mode": result.get("verifier_environment_mode"),
                "requested_model": result.get("config", {}).get("agent", {}).get("model_name"),
                "agent_timeout_multiplier": (
                    result.get("config", {}).get("agent_timeout_multiplier")
                    or result.get("config", {}).get("timeout_multiplier", 1.0)
                ),
                "arm": result.get("config", {}).get("agent", {}).get("kwargs", {}).get("arm"),
                "started_at": result.get("started_at"),
                "finished_at": result.get("finished_at"),
                "runtime_fingerprint": _load(fingerprint_path) if fingerprint_path.is_file() else None,
                "reward": reward,
                "exception": result.get("exception_info"),
                "tool_calls": report.get("tool_calls", []),
                "failures": report.get("failures", []),
                "relay_atof": (artifact_root / "relay" / "atof" / "events.jsonl").exists(),
                "relay_atif": any((artifact_root / "relay" / "atif").glob("*.json")),
                "relay_trajectory_ids": sorted(relay_ids),
            }
        )
    numeric = [float(trial["reward"]) for trial in trials if trial["reward"] is not None]
    tool_call_counts = [len(trial["tool_calls"]) for trial in trials]
    summary = {
        "schema": "hermes-harbor-job-summary-v1",
        "job_dir": str(args.job_dir),
        "job_started_at": job_result.get("started_at"),
        "job_finished_at": job_result.get("finished_at"),
        "runtime": runtime_records[0] if len(runtime_records) == 1 else runtime_records,
        "trials": trials,
        "counts": {
            "total": len(trials),
            "passed": sum(trial["reward"] == 1.0 for trial in trials),
            "exceptions": sum(bool(trial["exception"]) for trial in trials),
            "relay_complete": sum(
                bool(trial["relay_atof"] and trial["relay_atif"]) for trial in trials
            ),
        },
        "mean_reward": mean(numeric) if numeric else None,
        "tool_calls": {
            "total": sum(tool_call_counts),
            "mean_per_trial": mean(tool_call_counts) if tool_call_counts else None,
        },
    }
    rendered = json.dumps(summary, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if trials and not summary["counts"]["exceptions"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
