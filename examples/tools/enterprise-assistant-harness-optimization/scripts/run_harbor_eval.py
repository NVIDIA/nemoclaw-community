#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run one baseline or candidate arm on the development or held-out Harbor set."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_job_result(job_dir: Path, expected_trials: int) -> int:
    """Harbor's successful CLI exit does not establish successful trial execution."""
    result_path = job_dir / "result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Cannot verify the recorded Harbor job: {result_path}: {exc}", file=sys.stderr)
        return 1
    stats = result.get("stats", {})
    if (not result.get("finished_at")
            or stats.get("n_completed_trials") != expected_trials
            or stats.get("n_errored_trials") != 0):
        print(f"Harbor job is incomplete or infrastructure-invalid: {result_path}. "
              "Retain its artifacts and inspect trial exceptions before continuing.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--split", choices=("development", "held-out"), required=True)
    parser.add_argument(
        "--runtime",
        choices=("openshell", "direct"),
        default="openshell",
        help="Run Hermes in OpenShell (default) or directly in the Harbor task image.",
    )
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--agent-timeout-multiplier", type=float, default=2.0,
                        help="Shared Harbor agent-phase budget multiplier (includes sandbox/artifact overhead).")
    parser.add_argument("--harbor", default="harbor")
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / ".runs" / "harbor")
    parser.add_argument("--job-name")
    parser.add_argument(
        "--suite", type=Path, default=ROOT / "evals" / "flywheel-eval-set-v3.json"
    )
    parser.add_argument(
        "--tasks-dir", type=Path, default=ROOT / "evals" / "harbor-tasks-v3"
    )
    parser.add_argument("--model", default="nvidia/nemotron-3-ultra-550b-a55b")
    parser.add_argument("--openshell-bin", default="openshell")
    parser.add_argument("--openshell-image", default="hermes-flywheel-openshell:0.3")
    parser.add_argument("--openshell-provider", default="hermes-nvidia")
    parser.add_argument("--provider-base-url", default="")
    args = parser.parse_args()
    if args.attempts < 1 or args.concurrency < 1:
        parser.error("--attempts and --concurrency must be positive")
    if args.agent_timeout_multiplier <= 0:
        parser.error("--agent-timeout-multiplier must be positive")

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    case_kind = "held_out" if args.split == "held-out" else "development"
    case_ids = [case["id"] for case in suite["cases"] if case["case_kind"] == case_kind]
    if not case_ids:
        parser.error(f"the selected suite has no {args.split} cases")
    job_name = args.job_name or f"{args.arm}-{args.split}"
    agent = (
        "harbor_agents.openshell_hermes:OpenShellHermesFlywheel"
        if args.runtime == "openshell"
        else "harbor_agents.hermes_flywheel:HermesFlywheel"
    )
    command = [
        args.harbor,
        "run",
        "-p",
        str(args.tasks_dir),
        "-a",
        agent,
        "--ak",
        f"arm={args.arm}",
        "-m",
        args.model,
        "--jobs-dir",
        str(args.jobs_dir),
        "--job-name",
        job_name,
        "--n-attempts",
        str(args.attempts),
        "--n-concurrent",
        str(args.concurrency),
        "--agent-timeout-multiplier",
        str(args.agent_timeout_multiplier),
        "--yes",
    ]
    if args.runtime == "openshell":
        command.extend(("--ak", f"openshell_bin={args.openshell_bin}"))
        command.extend(("--ak", f"openshell_image={args.openshell_image}"))
        command.extend(("--ak", f"openshell_provider={args.openshell_provider}"))
        if args.provider_base_url:
            command.extend(("--ak", f"provider_base_url={args.provider_base_url}"))
    for case_id in case_ids:
        command.extend(("--include-task-name", case_id))
    print(
        json.dumps(
            {
                "arm": args.arm,
                "split": args.split,
                "runtime": args.runtime,
                "cases": case_ids,
                "job": job_name,
            }
        )
    )
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(ROOT)
    )
    return_code = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    if return_code:
        return return_code
    return check_job_result(args.jobs_dir / job_name, len(case_ids) * args.attempts)


if __name__ == "__main__":
    raise SystemExit(main())
