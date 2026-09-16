#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Summarize the payload-free execution shape of an ATIF trajectory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

Trajectory = dict[str, Any]


def load_trajectory(path: Path) -> Trajectory:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: invalid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return value


def display_value(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "unknown"


def count_step_llm_calls(step: Trajectory, index: int) -> int:
    value = step.get("llm_call_count", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"step {index}: invalid llm_call_count")
    return value


def count_requested_step_tool_calls(step: Trajectory, index: int) -> int:
    value = step.get("tool_calls", [])
    if not isinstance(value, list):
        raise ValueError(f"step {index}: invalid tool_calls")
    return len(value)


def summarize(trajectory: Trajectory) -> dict[str, str | int]:
    agent = trajectory.get("agent", {})
    if not isinstance(agent, dict):
        raise ValueError("invalid agent")

    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise ValueError("invalid steps")

    llm_calls = 0
    requested_tool_calls = 0
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"step {index}: expected a JSON object")
        llm_calls += count_step_llm_calls(step, index)
        requested_tool_calls += count_requested_step_tool_calls(step, index)

    return {
        "agent": display_value(agent.get("name")),
        "model": display_value(agent.get("model_name")),
        "steps": len(steps),
        "llm_calls": llm_calls,
        "requested_tool_calls": requested_tool_calls,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize the execution shape of an ATIF trajectory."
    )
    parser.add_argument("trajectory", type=Path, help="Path to an ATIF trajectory JSON file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = summarize(load_trajectory(args.trajectory))
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"trajectory: {args.trajectory}")
    for label, value in summary.items():
        print(f"{label.replace('_', ' ')}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
