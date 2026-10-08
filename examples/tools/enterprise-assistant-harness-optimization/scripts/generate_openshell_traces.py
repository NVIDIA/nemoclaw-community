#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Collect fresh, unscored baseline traces from the OpenShell deployment."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbor_agents.openshell_hermes import OpenShellHermesFlywheel
from scripts.production_workload import validate_matrix


async def collect(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    scenarios = matrix["scenarios"]
    if args.case:
        requested = set(args.case)
        known = {scenario["id"] for scenario in scenarios}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"unknown matrix case(s): {', '.join(unknown)}")
        scenarios = [scenario for scenario in scenarios if scenario["id"] in requested]
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    jobs = [
        (index, scenario, attempt)
        for index, (scenario, attempt) in enumerate(
            (
                (scenario, attempt)
                for scenario in scenarios
                for attempt in range(1, args.attempts + 1)
            ),
            start=1,
        )
    ]
    print(
        f"Collecting {len(jobs)} trace(s) from {len(scenarios)} request(s), "
        f"concurrency {args.concurrency}",
        file=sys.stderr,
        flush=True,
    )

    async def run_one(index: int, scenario: dict[str, Any], attempt: int) -> None:
        case_id = scenario["id"]
        run_id = f"{case_id}-{attempt:02d}"
        run_dir = output / run_id
        errors: list[str] = []

        def progress(message: str) -> None:
            print(f"[{index}/{len(jobs)}] {run_id}: {message}", file=sys.stderr, flush=True)

        progress("starting")
        for retry in range(args.retries + 1):
            if retry:
                progress(f"retry {retry + 1}/{args.retries + 1}")
            try_dir = run_dir if retry == 0 else run_dir / f"retry-{retry:02d}"
            agent = OpenShellHermesFlywheel(
                logs_dir=try_dir / "agent",
                model_name=args.model,
                arm="baseline",
                openshell_bin=args.openshell_bin,
                openshell_image=args.openshell_image,
                openshell_provider=args.openshell_provider,
                provider_base_url=args.provider_base_url,
            )
            agent.session_id = f"source-{run_id}-try-{retry + 1}"
            try:
                async with semaphore:
                    await agent._host_command([args.openshell_bin, "status"], timeout=30)
                    await agent.execute_openshell(
                        scenario["prompt"], try_dir / "artifacts"
                    )
                relay_paths = sorted(
                    str(path.relative_to(output))
                    for path in (try_dir / "artifacts" / "relay").rglob("*.json")
                )
                if not relay_paths:
                    raise RuntimeError(
                        f"OpenShell run produced no Relay ATIF: {run_id}"
                    )
            except (OSError, RuntimeError, TimeoutError) as exc:
                detail = f"{type(exc).__name__}: {str(exc)[-1000:]}"
                errors.append(detail)
                progress(f"attempt {retry + 1} failed: {detail.splitlines()[-1][:240]}")
                continue

            call_log = try_dir / "artifacts" / "tool-calls.jsonl"
            records.append(
                {
                    "run_id": run_id,
                    "logical_case_id": case_id,
                    "behavior_family": scenario.get("behavior_family"),
                    "attempt": attempt,
                    "runtime_attempts": retry + 1,
                    "prompt": scenario["prompt"],
                    "relay_atif": relay_paths,
                    "mcp_call_log": (
                        str(call_log.relative_to(output))
                        if call_log.is_file()
                        else None
                    ),
                }
            )
            progress("finished")
            return

        progress("failed")
        failures.append(
            {
                "run_id": run_id,
                "logical_case_id": case_id,
                "attempt": attempt,
                "runtime_attempts": args.retries + 1,
                "errors": errors,
            }
        )

    await asyncio.gather(
        *(run_one(index, scenario, attempt) for index, scenario, attempt in jobs)
    )
    return (
        sorted(records, key=lambda item: item["run_id"]),
        sorted(failures, key=lambda item: item["run_id"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix", type=Path, default=ROOT / "experiments" / "production-trace-matrix-v3.json"
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry each logical run after an infrastructure/model timeout",
    )
    parser.add_argument("--case", action="append", help="Run only this matrix case (repeatable).")
    parser.add_argument("--output", type=Path, default=ROOT / ".runs" / "source-traces")
    parser.add_argument("--model", default="nvidia/nemotron-3-ultra-550b-a55b")
    parser.add_argument("--openshell-bin", default="openshell")
    parser.add_argument("--openshell-image", default="hermes-flywheel-openshell:0.3")
    parser.add_argument("--openshell-provider", default="hermes-nvidia")
    parser.add_argument("--provider-base-url", default="")
    args = parser.parse_args()
    if args.attempts < 1 or args.concurrency < 1 or args.retries < 0:
        parser.error("--attempts/concurrency must be positive and --retries nonnegative")
    if not args.matrix.is_file():
        parser.error(f"matrix not found: {args.matrix}")

    try:
        matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
        validate_matrix(matrix, allow_partial=bool(args.case))
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    requested = set(args.case or [])
    selected = [
        scenario
        for scenario in matrix["scenarios"]
        if not requested or scenario["id"] in requested
    ]
    unknown = requested - {scenario["id"] for scenario in selected}
    if unknown:
        parser.error(f"unknown matrix case(s): {', '.join(sorted(unknown))}")
    if args.attempts != 1 and not args.case:
        parser.error(
            "production traces use one run per distinct request; add matrix rows instead of repeating prompts"
        )

    records, failures = asyncio.run(collect(args))
    matrix_path = args.matrix.resolve()
    try:
        matrix_label = str(matrix_path.relative_to(ROOT))
    except ValueError:
        matrix_label = str(matrix_path)
    manifest = {
        "schema": "openshell-source-traces-v2",
        "runtime": "openshell",
        "mcp_transport": "streamable-http",
        "mcp_endpoint": "host.openshell.internal:8765",
        "arm": "baseline",
        "model": args.model,
        "matrix": matrix_label,
        "distinct_requests": len(selected),
        "runs": records,
        "failures": failures,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "runs": len(records),
                "failures": len(failures),
            }
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
