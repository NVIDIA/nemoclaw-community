#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate the fresh production-trace corpus and its index."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

MIN_TRACES = 36
MAX_TRACES = 48
MIN_DISTINCT_REQUESTS = 30
MIN_BEHAVIOR_FAMILIES = 5


def _user_prompt(trace: dict[str, Any]) -> str:
    return "\n".join(
        str(step.get("message", "")).strip()
        for step in trace.get("steps", [])
        if step.get("source") == "user" and str(step.get("message", "")).strip()
    )


def validate(index_path: Path) -> list[str]:
    errors: list[str] = []
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema") != "enterprise-trace-corpus-v2":
        errors.append("unsupported corpus schema")
    bundle_path = index_path.parent / "insights.jsonl"
    if not bundle_path.is_file():
        errors.append("missing Insights input bundle")
    elif index.get("insights_sha256") != hashlib.sha256(bundle_path.read_bytes()).hexdigest():
        errors.append("Insights input bundle digest differs from index")
    records = index.get("traces")
    if not isinstance(records, list):
        return errors + ["traces must be a list"]
    if not MIN_TRACES <= len(records) <= MAX_TRACES:
        errors.append(f"source corpus must contain {MIN_TRACES}–{MAX_TRACES} traces; found {len(records)}")

    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    indexed_prompts: dict[str, str] = {}
    prompts: list[str] = []
    families: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, dict):
            errors.append("every index record must be an object")
            continue
        raw_path = record.get("path")
        if not isinstance(raw_path, str) or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            errors.append(f"invalid relative trace path: {raw_path!r}")
            continue
        if raw_path in seen_paths:
            errors.append(f"duplicate trace path: {raw_path}")
        seen_paths.add(raw_path)
        trace_path = index_path.parent / raw_path
        if not trace_path.is_file():
            errors.append(f"missing trace: {raw_path}")
            continue
        if record.get("sha256") != hashlib.sha256(trace_path.read_bytes()).hexdigest():
            errors.append(f"{raw_path}: trace digest differs from index")
        trace: dict[str, Any] = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace.get("schema_version") != "ATIF-v1.7":
            errors.append(f"{raw_path}: expected ATIF-v1.7")
        trace_id = trace.get("trajectory_id")
        if trace_id != record.get("trace_id"):
            errors.append(f"{raw_path}: trace_id does not match trajectory_id")
        if trace_id in seen_ids:
            errors.append(f"duplicate trajectory_id: {trace_id}")
        seen_ids.add(trace_id)
        case_id = record.get("logical_case_id")
        if case_id != trace.get("extra", {}).get("logical_case_id"):
            errors.append(f"{raw_path}: logical_case_id mismatch")
        family = record.get("behavior_family")
        if not isinstance(family, str) or not family:
            errors.append(f"{raw_path}: behavior_family is required")
        else:
            families[family] += 1
        prompt = _user_prompt(trace)
        if not prompt:
            errors.append(f"{raw_path}: source user request is missing")
        elif record.get("prompt") != prompt:
            errors.append(f"{raw_path}: indexed prompt differs from the recorded user request")
        else:
            prompts.append(prompt.casefold())
            indexed_prompts[trace_id] = prompt

    if bundle_path.is_file():
        try:
            bundle = [json.loads(line) for line in bundle_path.read_text().splitlines() if line.strip()]
        except ValueError:
            errors.append("Insights input bundle must contain valid JSONL")
        else:
            input_ids = [trace.get("id") for trace in bundle if isinstance(trace, dict)]
            if (len(input_ids) != len(bundle) or len(input_ids) != len(records)
                    or any(not isinstance(value, str) or not value for value in input_ids)
                    or len(set(input_ids)) != len(input_ids) or set(input_ids) != seen_ids):
                errors.append("Insights input IDs/count differ from indexed source traces")
            for trace in bundle:
                if not isinstance(trace, dict):
                    continue
                attributes = trace.get("attributes") or {}
                if not isinstance(attributes, dict):
                    errors.append("Insights input attributes must be an object")
                    continue
                prompt = attributes.get("task_text") or attributes.get("prompt")
                if prompt != indexed_prompts.get(trace.get("id")):
                    errors.append("Insights input prompt differs from indexed source trace")

    if len(set(prompts)) < MIN_DISTINCT_REQUESTS:
        errors.append(
            f"need at least {MIN_DISTINCT_REQUESTS} distinct user requests; found {len(set(prompts))}"
        )
    if len(prompts) != len(set(prompts)):
        errors.append("source prompts must be distinct; increase workload variety instead of repeating requests")
    if len(families) < MIN_BEHAVIOR_FAMILIES:
        errors.append(f"need at least {MIN_BEHAVIOR_FAMILIES} behavior families; found {len(families)}")
    if any(count < 4 for count in families.values()):
        errors.append("each behavior family must have at least four source traces")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    args = parser.parse_args()
    errors = validate(args.index)
    if errors:
        print("Trace corpus validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    index = json.loads(args.index.read_text(encoding="utf-8"))
    family_count = len({record["behavior_family"] for record in index["traces"]})
    print(f"Trace corpus validation passed: {len(index['traces'])} distinct requests across {family_count} behavior families")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
