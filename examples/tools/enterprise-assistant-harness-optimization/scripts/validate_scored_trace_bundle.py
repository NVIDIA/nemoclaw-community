#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate a repeated Harbor baseline bundle before Trace Analyst ingestion."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def validate(path: Path, *, minimum_attempts: int = 3) -> list[str]:
    errors: list[str] = []
    traces = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    ids = [trace.get("id") for trace in traces]
    cases = [trace.get("attributes", {}).get("logical_case_id") for trace in traces]
    rewards = [trace.get("evaluator_results", {}).get("harbor.reward") for trace in traces]
    if not traces:
        errors.append("scored baseline bundle is empty")
        return errors
    if len(set(ids)) != len(ids) or any(not value for value in ids):
        errors.append("trace IDs must be present and unique")
    if any(not value for value in cases):
        errors.append("every scored trace needs its Harbor task ID")
    if any(value not in {0, 1, 0.0, 1.0} for value in rewards):
        errors.append("every scored trace needs a binary harbor.reward")
    counts = Counter(cases)
    if len(counts) < 2:
        errors.append("scored baseline bundle must cover multiple development tasks")
    if counts and (min(counts.values()) < minimum_attempts or len(set(counts.values())) != 1):
        errors.append(
            f"each development task must have the same number of traces, at least {minimum_attempts}; found {dict(counts)}"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--minimum-attempts", type=int, default=3)
    args = parser.parse_args()
    if args.minimum_attempts < 1:
        parser.error("--minimum-attempts must be positive")
    errors = validate(args.path, minimum_attempts=args.minimum_attempts)
    if errors:
        print("Scored trace bundle validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    traces = [json.loads(line) for line in args.path.read_text(encoding="utf-8").splitlines() if line]
    cases = {trace["attributes"]["logical_case_id"] for trace in traces}
    print(f"Scored trace bundle validation passed: {len(traces)} attempts across {len(cases)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
