#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Convert Trace Analyst canonical JSONL into a compact public ATIF corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp import EnterpriseWorld, ToolRegistry

MCP_PREFIXES = ("mcp__pa_style_enterprise__", "mcp__enterprise_world__")


@lru_cache(maxsize=1)
def _fixture_schemas() -> dict[str, dict[str, Any]]:
    registry = ToolRegistry(
        EnterpriseWorld.from_path(ROOT / "fixtures" / "world-v2.json"), catalog="extended"
    )
    return {schema["name"]: schema["inputSchema"] for schema in registry.schemas()}


def _is_fixture_tool(name: str) -> bool:
    return name.startswith(MCP_PREFIXES) or name in _fixture_schemas()


def _tool_catalog(attributes: dict[str, Any], spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve captured schemas and fill dynamic MCP catalog gaps explicitly."""
    catalog = dict(attributes.get("tool_catalog", {}))
    fixture_schemas = dict(_fixture_schemas())
    for name, schema in _fixture_schemas().items():
        suffix = name.replace(".", "_")
        for prefix in MCP_PREFIXES:
            fixture_schemas[f"{prefix}{suffix}"] = schema
    for span in spans:
        name = span.get("tool_name")
        if not isinstance(name, str):
            continue
        if not _is_fixture_tool(name):
            # The public corpus keeps the call name as trajectory evidence but
            # redacts its payload. Do not retain a schema that would make the
            # explicit redaction look like a malformed original call.
            catalog[name] = {}
            continue
        if name in catalog:
            continue
        # Relay's LLM request catalog omitted dynamically discovered MCP tools.
        # Use the exact mock-server schema when one exists. For other executed
        # runtime helpers, retain only an empty contract because their payloads
        # are intentionally redacted from the public corpus.
        catalog[name] = fixture_schemas.get(name, {})
    return catalog


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _source_prompt(attributes: dict[str, Any]) -> str:
    """Support both canonical task_text and the ATOF adapter's prompt field."""
    for key in ("task_text", "prompt"):
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def convert(trace: dict[str, Any], *, collection: str, ordinal: int) -> dict[str, Any]:
    attributes = trace.get("attributes", {})
    spans = sorted(trace.get("root_spans", []), key=lambda span: span.get("start_time", ""))
    prompt = _source_prompt(attributes)
    steps: list[dict[str, Any]] = [
        {
            "step_id": 1,
            "timestamp": spans[0].get("start_time") if spans else None,
            "source": "user",
            "message": prompt,
        }
    ]
    for span in spans:
        if span.get("kind") != "TOOL" or not isinstance(span.get("tool_name"), str):
            continue
        tool_name = span["tool_name"]
        fixture_tool = _is_fixture_tool(tool_name)
        tool_call = span.get("tool_call") if isinstance(span.get("tool_call"), dict) else {}
        call_id = str(tool_call.get("call_id") or span.get("id") or len(steps))
        arguments = span.get("input", {})
        output = span.get("output")
        if not fixture_tool:
            arguments = {"redacted": "non-fixture tool input removed from public corpus"}
            output = "[redacted: non-fixture tool output removed from public corpus]"
        steps.append(
            {
                "step_id": len(steps) + 1,
                "timestamp": span.get("start_time"),
                "source": "agent",
                "message": "",
                "tool_calls": [
                    {
                        "tool_call_id": call_id,
                        "function_name": tool_name,
                        "arguments": arguments if isinstance(arguments, dict) else {},
                    }
                ],
                "observation": {
                    "results": [{"source_call_id": call_id, "content": _content(output)}]
                },
            }
        )
    model = attributes.get("model") or (attributes.get("agent") or {}).get("model_name")
    source_metrics = attributes.get("final_metrics")
    metrics = dict(source_metrics) if isinstance(source_metrics, dict) else {}
    steps.append(
        {
            "step_id": len(steps) + 1,
            "timestamp": spans[-1].get("end_time") if spans else None,
            "source": "agent",
            "model_name": model,
            "message": attributes.get("final_answer", ""),
        }
    )
    trace_id = str(trace["id"])
    metrics["total_steps"] = len(steps)
    return {
        "schema_version": "ATIF-v1.7",
        "session_id": trace_id,
        "trajectory_id": trace_id,
        "agent": {
            "name": "Hermes-enterprise-world",
            "version": "tutorial-baseline",
            "model_name": model,
        },
        "final_metrics": metrics,
        "extra": {
            "logical_case_id": attributes.get("logical_case_id"),
            "observed_verdict": attributes.get("observed_verdict"),
            "metrics": attributes.get("metrics", {}),
            "trajectory_contract": attributes.get("trajectory_contract", {}),
            "evaluator_results": trace.get("evaluator_results", {}),
            # Preserve the catalog Relay captured so a later Insights pass can
            # distinguish a real unknown tool from missing instrumentation.
            "tool_catalog": _tool_catalog(attributes, spans),
            "collection": collection,
            "collection_ordinal": ordinal,
            "normalization": {
                "source_format": "NeMo canonical trace JSONL derived from Relay",
                "source_trace_id": trace_id,
                "losses": [
                    "Span nesting was flattened into sequential ATIF steps.",
                    "Non-fixture tool inputs and outputs were replaced by explicit redaction markers.",
                    "total_steps counts the projected public trajectory, not the original span tree.",
                ],
                "uncertainties": (
                    (["Model identity was not recorded by the source."] if model in (None, "unknown") else [])
                    + (["Token totals were unavailable in mapped source metrics; they were not inferred as zero."]
                       if not isinstance(source_metrics, dict) else [])
                ),
            },
        },
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=ROOT / "experiments" / "production-trace-matrix-v3.json",
        help="Source workload matrix used to label behavior families.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    family_by_case = {
        scenario["id"]: scenario["behavior_family"]
        for scenario in matrix["scenarios"]
        if scenario.get("behavior_family")
    }
    index = []
    public_traces = []
    ordinal = 0
    for source in args.source:
        label, separator, raw_path = source.partition("=")
        if not separator or not label:
            raise SystemExit("--source must be LABEL=PATH")
        for line in Path(raw_path).read_text(encoding="utf-8").splitlines():
            trace = json.loads(line)
            case_id = trace.get("attributes", {}).get("logical_case_id")
            if not isinstance(case_id, str):
                raise ValueError("each source trace needs a logical_case_id")
            ordinal += 1
            filename = f"trace-{ordinal:03d}--{label}.atif.json"
            atif = convert(trace, collection=label, ordinal=ordinal)
            from pa_style_mock_mcp.insights import atif_to_insights_trace
            public_trace = atif_to_insights_trace(
                atif, logical_case_id=case_id,
                evaluator_results=trace.get("evaluator_results", {}),
            )
            public_traces.append(public_trace)
            (args.output / filename).write_text(
                json.dumps(atif, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            index.append(
                {
                    "path": filename,
                    "sha256": hashlib.sha256((args.output / filename).read_bytes()).hexdigest(),
                    "trace_id": atif["trajectory_id"],
                    "logical_case_id": case_id,
                    "collection": label,
                    "behavior_family": family_by_case.get(case_id),
                    "prompt": _source_prompt(trace.get("attributes", {})),
                }
            )
    (args.output / "insights.jsonl").write_text(
        "".join(json.dumps(trace, separators=(",", ":")) + "\n" for trace in public_traces),
        encoding="utf-8",
    )
    (args.output / "index.json").write_text(
        json.dumps({"schema": "enterprise-trace-corpus-v2", "traces": index,
                    "insights_sha256": hashlib.sha256((args.output / "insights.jsonl").read_bytes()).hexdigest()},
                   indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "traces": len(index)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
