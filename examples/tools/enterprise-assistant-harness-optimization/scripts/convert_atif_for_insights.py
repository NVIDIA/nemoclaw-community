#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Convert Relay ATIF files to standalone NeMo Insights canonical JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp.insights import atif_to_insights_trace

MCP_PREFIXES = ("mcp__pa_style_enterprise__", "mcp__enterprise_world__")


def _canonical_tool_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    for prefix in MCP_PREFIXES:
        if value.startswith(prefix):
            short = value[len(prefix) :]
            domain, separator, operation = short.partition("_")
            return f"{domain}.{operation}" if separator else short
    return value


def _canonicalize_tool_names(trace: dict[str, Any]) -> None:
    """Align Relay's Hermes MCP identifiers with evaluator-facing tool names."""
    attributes = trace.get("attributes", {})
    catalog = attributes.get("tool_catalog", {})
    if isinstance(catalog, dict):
        normalized: dict[str, Any] = {}
        for name, schema in catalog.items():
            canonical = _canonical_tool_name(name)
            if isinstance(canonical, str):
                normalized.setdefault(canonical, schema)
        attributes["tool_catalog"] = normalized
    for span in trace.get("root_spans", []):
        if isinstance(span, dict):
            span["tool_name"] = _canonical_tool_name(span.get("tool_name"))


def _files(inputs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for item in inputs:
        if item.is_dir():
            found.extend(
                path
                for path in sorted(item.rglob("*.json"))
                if path.name.endswith(".atif.json")
                or (path.parent.name == "atif" and path.parent.parent.name == "relay")
            )
        elif item.is_file():
            found.append(item)
        else:
            raise FileNotFoundError(item)
    return found


def _harbor_context(path: Path) -> tuple[str | None, dict[str, object]]:
    """Resolve case ID and evaluator results from an enclosing Harbor trial."""
    for parent in path.parents:
        result_path = parent / "result.json"
        if not result_path.is_file():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        task_name = result.get("task_name")
        case_id = task_name.rsplit("/", 1)[-1] if isinstance(task_name, str) else None
        reward = result.get("verifier_result", {}).get("rewards", {}).get("reward")
        evaluator_results: dict[str, object] = {"harbor.reward": reward}
        report_path = parent / "verifier" / "report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            evaluator_results["harbor.passed"] = report.get("passed")
            evaluator_results["harbor.failures"] = report.get("failures", [])
        return case_id, evaluator_results
    return None, {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case-id-from-parent",
        action="store_true",
        help="Use the ATIF file's containing directory as logical_case_id.",
    )
    parser.add_argument(
        "--case-id-from-stem",
        action="store_true",
        help="Use each ATIF filename before .atif.json as logical_case_id.",
    )
    args = parser.parse_args()
    if args.case_id_from_parent and args.case_id_from_stem:
        parser.error("choose at most one case-ID inference mode")

    files = _files(args.inputs)
    if not files:
        raise SystemExit("no ATIF JSON files found")
    traces = []
    seen: set[str] = set()
    for path in files:
        trajectory = json.loads(path.read_text())
        if args.case_id_from_parent:
            case_id = path.parent.parent.parent.name
        elif args.case_id_from_stem:
            suffix = ".atif.json"
            case_id = path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem
        else:
            harbor_case_id, evaluator_results = _harbor_context(path)
            case_id = trajectory.get("extra", {}).get("logical_case_id") or harbor_case_id
        if args.case_id_from_parent or args.case_id_from_stem:
            _, evaluator_results = _harbor_context(path)
        trace = atif_to_insights_trace(
            trajectory,
            logical_case_id=case_id,
            evaluator_results=evaluator_results,
        )
        _canonicalize_tool_names(trace)
        if trace["id"] in seen:
            raise ValueError(f"duplicate trace id: {trace['id']}")
        seen.add(trace["id"])
        traces.append(trace)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(trace, separators=(",", ":")) + "\n" for trace in traces))
    print(f"Converted {len(traces)} ATIF trajectories to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
