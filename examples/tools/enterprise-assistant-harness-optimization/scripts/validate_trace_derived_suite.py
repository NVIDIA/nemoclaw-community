#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate a human-reviewed, Insights-guided Eval Author suite and split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MIN_SOURCE_TRACES = 36
MAX_SOURCE_TRACES = 48


def validate(suite: dict[str, Any], *, require_review: bool = True) -> list[str]:
    errors: list[str] = []
    if suite.get("suite_version") != "3.0":
        errors.append("suite_version must be 3.0")
    generation = suite.get("generation", {})
    if generation.get("method") != "codex-with-nemo-eval-author":
        errors.append("generation.method must record Codex using Eval Author")
    if not generation.get("selection_rationale"):
        errors.append("generation.selection_rationale is required")
    review_status = generation.get("review_status")
    if review_status not in ("human_reviewed", "pending_human_review"):
        errors.append("generation.review_status must be human_reviewed or pending_human_review")
    elif require_review and review_status != "human_reviewed":
        errors.append("generation.review_status must record human review")
    if generation.get("split_frozen_before_candidate") is not True:
        errors.append("development/held-out split must be frozen before candidate design")
    source_count = generation.get("source_trace_count")
    if not isinstance(source_count, int) or not MIN_SOURCE_TRACES <= source_count <= MAX_SOURCE_TRACES:
        errors.append(f"source_trace_count must be between {MIN_SOURCE_TRACES} and {MAX_SOURCE_TRACES}")
    if not generation.get("source_corpus"):
        errors.append("generation.source_corpus is required")
    if not generation.get("production_insights"):
        errors.append("generation.production_insights is required")

    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("suite requires at least one case")
        return errors
    all_case_ids = {case.get("id") for case in cases if isinstance(case, dict)}
    kinds = {case.get("id"): case.get("case_kind") for case in cases if isinstance(case, dict)}
    case_ids: set[str] = set()
    source_refs: set[str] = set()
    development_count = 0
    held_out_count = 0
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            errors.append(f"case ID missing or duplicated: {case_id!r}")
        case_ids.add(case_id)
        provenance = case.get("provenance", {})
        trace_ref = provenance.get("trace_ref")
        if not isinstance(trace_ref, str) or not trace_ref.endswith(".atif.json"):
            errors.append(f"case {case_id} needs one local ATIF trace_ref")
        elif trace_ref in source_refs:
            errors.append(f"case {case_id} reuses another task's source trace")
        else:
            source_refs.add(trace_ref)
        insight_refs = provenance.get("insight_refs")
        if not isinstance(insight_refs, list) or not insight_refs or not all(
            isinstance(item, str) and item for item in insight_refs
        ):
            errors.append(f"case {case_id} needs production insight references")
        if not case.get("input") or not isinstance(case.get("expectations"), dict):
            errors.append(f"case {case_id} needs an input and objective expectations")
        if not isinstance(case.get("relevant_experience"), str) or not case["relevant_experience"].strip():
            errors.append(f"case {case_id} needs human-reviewed relevant experience")
        if not isinstance(case.get("behavior_family"), str) or not case["behavior_family"]:
            errors.append(f"case {case_id} needs its reviewed behavior family")
        task_ref = provenance.get("harbor_task_ref")
        task_path = Path(task_ref) if isinstance(task_ref, str) else None
        if not task_path or task_path.is_absolute() or ".." in task_path.parts or task_path.name != case_id:
            errors.append(f"case {case_id} needs its Harbor task reference")
        case_kind = case.get("case_kind")
        if case_kind == "development":
            development_count += 1
        elif case_kind == "held_out":
            held_out_count += 1
            parents = provenance.get("held_out_from_case_ids")
            if not isinstance(parents, list) or not parents or not all(
                parent in all_case_ids and parent != case_id and kinds.get(parent) == "development"
                for parent in parents
            ):
                errors.append(f"held-out case {case_id} needs a development behavior parent")
        else:
            errors.append(f"case {case_id} case_kind must be development or held_out")
    if not development_count:
        errors.append("suite needs at least one development task")
    if not held_out_count:
        errors.append("suite needs at least one held-out task")
    if len(source_refs) != len(cases):
        errors.append("each case must use a distinct source trace")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument(
        "--allow-unreviewed", action="store_true",
        help="Validate an experimental draft for technical runs; does not establish readiness.",
    )
    args = parser.parse_args()
    errors = validate(
        json.loads(args.suite.read_text(encoding="utf-8")),
        require_review=not args.allow_unreviewed,
    )
    if errors:
        print("Trace-derived suite validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    development = sum(case["case_kind"] == "development" for case in suite["cases"])
    held_out = sum(case["case_kind"] == "held_out" for case in suite["cases"])
    print(f"Eval suite validation passed: {development} development tasks, {held_out} held out")
    if suite["generation"]["review_status"] != "human_reviewed":
        print("Experimental draft: human task and Relevant experience review remains pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
