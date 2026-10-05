#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Convert real Relay ATOF turns to explicitly loss-recorded ATIF-v1.7 files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp.atif import atof_events_to_atif_trajectories
from pa_style_mock_mcp.jsonl import read_relay_jsonl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atof", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--redact-non-fixture-tools",
        action="store_true",
        help="Remove local/runtime tool inputs and outputs for a public fixture-only bundle.",
    )
    args = parser.parse_args()

    events, recovered_lines = read_relay_jsonl(args.atof)
    trajectories = atof_events_to_atif_trajectories(
        events, redact_non_fixture_tools=args.redact_non_fixture_tools
    )
    if not trajectories:
        raise SystemExit("no completed hermes.turn scopes found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for trajectory in trajectories:
        target = args.output_dir / f"trajectory-{trajectory['trajectory_id']}.json"
        target.write_text(json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n")
    if recovered_lines:
        print(f"Recovered complete records after interrupted writes on lines {recovered_lines}")
    print(f"Converted {len(trajectories)} completed Hermes turns to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
