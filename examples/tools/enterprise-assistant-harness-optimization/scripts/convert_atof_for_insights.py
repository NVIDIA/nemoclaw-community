#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Convert a Relay ATOF stream into Trace Analyst canonical JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp.insights import apply_runner_outcomes, atof_events_to_insights_traces
from pa_style_mock_mcp.jsonl import read_relay_jsonl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--atof",
        type=Path,
        action="append",
        required=True,
        help="Relay ATOF JSONL file or directory containing per-run events.jsonl files; repeatable.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument(
        "--responses",
        type=Path,
        help="Matrix-runner response directory used to preserve caller-visible timeout outcomes.",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Include bounded Hermes turns without a closing Relay event as scored failures.",
    )
    args = parser.parse_args()

    sources: list[Path] = []
    for source in args.atof:
        if source.is_dir():
            sources.extend(sorted(source.rglob("events.jsonl")))
        else:
            sources.append(source)
    if not sources:
        raise SystemExit("no Relay ATOF JSONL files found")
    events = []
    recovered_lines = []
    for source in sources:
        source_events, source_recovered = read_relay_jsonl(source)
        events.extend(source_events)
        recovered_lines.extend(source_recovered)
    prompt_case_ids = None
    case_required_signals = None
    if args.matrix:
        matrix = json.loads(args.matrix.read_text())
        prompt_case_ids = {scenario["prompt"]: scenario["id"] for scenario in matrix["scenarios"]}
        case_required_signals = {
            scenario["id"]: scenario.get("signals", []) for scenario in matrix["scenarios"]
        }
    traces = atof_events_to_insights_traces(
        events,
        prompt_case_ids=prompt_case_ids,
        case_required_signals=case_required_signals,
        include_incomplete=args.include_incomplete,
    )
    if args.responses:
        unique_records = {}
        for path in sorted(args.responses.glob("*.json")):
            record = json.loads(path.read_text())
            if not record.get("workspace"):
                continue
            key = (
                record.get("case_id"),
                record.get("trial"),
                record.get("attempt"),
                record.get("completed_at"),
            )
            unique_records[key] = record
        records = list(unique_records.values())
        apply_runner_outcomes(traces, records)
    if not traces:
        raise SystemExit("no completed hermes.turn scopes found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(trace, separators=(",", ":")) + "\n" for trace in traces))
    if recovered_lines:
        print(f"Recovered complete records after interrupted writes on lines {recovered_lines}")
    print(f"Converted {len(traces)} Hermes turns to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
