#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate the saved production-trace → Insights → Eval Author → A/B chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_task_products import validate as validate_task_products
from scripts.validate_trace_corpus import validate as validate_trace_corpus


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"artifact-chain validation failed: {message}")


def validate_run(root: Path, summary: dict[str, Any], case_ids: set[str], arm: str,
                 attempts: int) -> tuple[dict[str, int], set[str]]:
    require(bool(summary.get("job_finished_at")), "measured job is not terminal")
    require(summary.get("runtime", {}).get("name") == "openshell-hermes-flywheel",
            "measured agent runtime is not OpenShell Hermes")
    trials = summary.get("trials", [])
    require(len(trials) == len(case_ids) * attempts, "retained measured trial denominator differs")
    counts: Counter[str] = Counter()
    passed: Counter[str] = Counter()
    names: set[str] = set()
    common_fingerprints: set[str] = set()
    for trial in trials:
        task_id = str(trial.get("task", "")).rsplit("/", 1)[-1]
        name = trial.get("trial")
        require(task_id in case_ids and isinstance(name, str) and name not in names,
                "measured task/trial identity is missing, unexpected, or duplicated")
        names.add(name)
        counts[task_id] += 1
        reward = trial.get("reward")
        require(reward in (0, 1) and not trial.get("exception"), "invalid reward or runtime exception")
        passed[task_id] += int(reward)
        require(trial.get("arm") == arm, "measured arm differs from comparison")
        require(trial.get("verifier_environment_mode") == "separate", "measured verifier was not separate")
        require(trial.get("relay_atof") is True and trial.get("relay_atif") is True,
                "measured trial lacks complete Relay capture")
        proof = json.loads((root / "evals/task-proofs" / task_id / "result.json").read_text())
        require(trial.get("task_checksum") == proof["technical_validation"]["task_checksum"],
                f"{task_id}: measured Harbor checksum differs from the proven task")
        fingerprint = trial.get("runtime_fingerprint") or {}
        require(fingerprint.get("schema") == "hermes-runtime-fingerprint-v1", "missing runtime fingerprint")
        require(fingerprint.get("arm") == arm, "runtime fingerprint arm mismatch")
        require(bool(trial.get("requested_model"))
                and fingerprint.get("requested_model") == trial["requested_model"], "model identity mismatch")
        for field, relative in (("profile_sha256", f"profiles/{arm}-soul.md"),
                                ("policy_sha256", "openshell/policy.yaml"),
                                ("fixture_sha256", "fixtures/world-v2.json")):
            require(fingerprint.get(field) == digest(root / relative), f"runtime {field} drift")
        expected_mcp = {name: digest(root / "src/pa_style_mock_mcp" / name)
                        for name in ("tools.py", "world.py")}
        require(fingerprint.get("mcp_implementation_sha256") == expected_mcp,
                "measured host MCP implementation drift")
        timeout_multiplier = trial.get("agent_timeout_multiplier")
        require(isinstance(timeout_multiplier, (int, float)) and timeout_multiplier > 0,
                "missing or invalid Harbor agent-phase timeout multiplier")
        common = {key: value for key, value in fingerprint.items()
                  if key not in ("arm", "profile_sha256")}
        common["harbor_agent_timeout_multiplier"] = timeout_multiplier
        common_fingerprints.add(json.dumps(common, sort_keys=True))
    require(set(counts) == case_ids and all(value == attempts for value in counts.values()),
            "measured task repetition counts differ")
    require(summary.get("counts", {}).get("passed") == sum(passed.values()),
            "run summary pass count differs from individual Harbor rewards")
    return dict(passed), common_fingerprints


def validate(root: Path, *, require_review: bool = True) -> None:
    chain_path = root / "results" / "artifact-chain.json"
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    require(
        chain.get("schema") == "hermes-agent-optimization-artifact-chain-v3",
        "unsupported artifact chain schema",
    )
    runtime = chain.get("runtime", {})
    require(runtime.get("agent_sandbox") == "OpenShell", "Hermes must run in OpenShell")
    mcp = runtime.get("mcp", {})
    require(mcp.get("location") == "host_outside_sandbox", "MCP must be hosted outside OpenShell")
    require(mcp.get("transport") == "streamable-http", "measured MCP transport must be Streamable HTTP")
    require(mcp.get("host") == "host.openshell.internal", "unexpected OpenShell host bridge")
    require(set(mcp.get("ports", [])) == {8765}, "MCP ports differ from the OpenShell policy")

    stage_ids: set[str] = set()
    stage_paths: dict[str, Path] = {}
    for stage in chain.get("stages", []):
        stage_id = stage.get("id")
        require(isinstance(stage_id, str) and stage_id not in stage_ids, f"duplicate/invalid stage {stage_id}")
        require(set(stage.get("consumes", [])) <= stage_ids, f"{stage_id} consumes a missing or later stage")
        relative = Path(stage["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "unsafe artifact path")
        path = root / relative
        require(path.is_file(), f"missing artifact {stage['path']}")
        require(digest(path) == stage.get("sha256"), f"digest drift in {stage['path']}")
        stage_ids.add(stage_id)
        stage_paths[stage_id] = path

    required_stages = {
        "production_corpus", "production_insights", "eval_suite",
        "baseline_development_traces", "baseline_development_insights",
        "candidate_proposal", "candidate_profile", "measured_ab",
        "baseline_development_run", "candidate_development_run",
        "baseline_held_out_run", "candidate_held_out_run",
    }
    require(required_stages <= stage_ids, f"missing chain stages: {sorted(required_stages - stage_ids)}")

    corpus = json.loads(stage_paths["production_corpus"].read_text(encoding="utf-8"))
    corpus_errors = validate_trace_corpus(stage_paths["production_corpus"])
    require(not corpus_errors, f"production corpus integrity: {corpus_errors}")
    source_traces = corpus.get("traces", [])
    require(36 <= len(source_traces) <= 48, "production trace count must be 36–48")
    prompt_values = [str(record.get("prompt", "")).strip().casefold() for record in source_traces]
    require(all(prompt_values) and len(set(prompt_values)) == len(prompt_values), "source prompts must be nonempty and distinct")
    family_counts = Counter(record.get("behavior_family") for record in source_traces)
    require(len(family_counts) >= 5 and min(family_counts.values()) >= 4, "source corpus lacks family coverage")
    trace_paths = {record.get("path") for record in source_traces}

    suite = json.loads(stage_paths["eval_suite"].read_text(encoding="utf-8"))
    generation = suite.get("generation", {})
    require(generation.get("source_trace_count") == len(source_traces), "suite source denominator differs from corpus")
    review = generation.get("review_status")
    require(review in ("human_reviewed", "pending_human_review"), "invalid suite review state")
    require(not require_review or review == "human_reviewed", "suite requires human task/split review")
    require(generation.get("split_frozen_before_candidate") is True, "suite split was not frozen before candidate design")
    cases = suite.get("cases", [])
    dev_cases = [case for case in cases if case.get("case_kind") == "development"]
    held_cases = [case for case in cases if case.get("case_kind") == "held_out"]
    require(dev_cases and held_cases, "suite needs development and held-out tasks")
    seen_sources: set[str] = set()
    for case in cases:
        provenance = case.get("provenance", {})
        source_ref = provenance.get("trace_ref", "")
        trace_path = Path(source_ref)
        require(not trace_path.is_absolute() and ".." not in trace_path.parts, f"unsafe trace reference in {case.get('id')}")
        require(str(trace_path.relative_to("traces/world-v3/production")) in trace_paths,
                f"case {case.get('id')} source trace is not in the indexed production corpus")
        require(source_ref not in seen_sources, f"source trace reused for {case.get('id')}")
        seen_sources.add(source_ref)
        require(provenance.get("insight_refs"), f"case {case.get('id')} lacks production Insights provenance")
        require(case.get("relevant_experience"), f"case {case.get('id')} lacks relevant experience")

    proof_errors = validate_task_products(root, require_review=require_review)
    require(not proof_errors, "; ".join(proof_errors))
    freeze = json.loads((root / "results/experiment-freeze.json").read_text())
    contract_fields = ("id", "case_kind", "behavior_family", "input", "expectations", "provenance")
    contract = [{key: case[key] for key in contract_fields} for case in cases]
    contract_hash = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    require(contract_hash == freeze.get("evaluation_contract_sha256"),
            "evaluation contract differs from frozen design")
    require(freeze.get("candidate_frozen_before_held_out_execution") is True,
            "candidate was not frozen before held-out execution")
    require(set(freeze.get("development_task_ids", [])) == {case["id"] for case in dev_cases},
            "development membership differs from experiment freeze")
    require(set(freeze.get("held_out_task_ids", [])) == {case["id"] for case in held_cases},
            "held-out membership differs from experiment freeze")
    require(digest(stage_paths["candidate_profile"]) == freeze.get("candidate_profile_sha256"),
            "candidate profile differs from frozen design")
    require(set(freeze.get("candidate_basis", [])) == {
        stage_paths[name].relative_to(root).as_posix()
        for name in ("production_insights", "baseline_development_insights")
    }, "candidate basis differs from retained design reports")
    try:
        frozen_at = datetime.fromisoformat(freeze["recorded_at"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        require(False, "missing or invalid candidate freeze timestamp")

    verification_stages = {"verification_baseline_development_traces", "verification_baseline_development_insights"}
    require(not (verification_stages & stage_ids) or verification_stages <= stage_ids,
            "independent verification requires both its baseline bundle and report")
    bundle_stages = ["baseline_development_traces"]
    if verification_stages <= stage_ids:
        bundle_stages.append("verification_baseline_development_traces")
    for bundle_stage in bundle_stages:
        baseline_bundle = [json.loads(line) for line in stage_paths[bundle_stage].read_text().splitlines() if line.strip()]
        counts = Counter(trace.get("attributes", {}).get("logical_case_id") for trace in baseline_bundle)
        require(set(counts) == {case["id"] for case in dev_cases}, "scored baseline bundle task IDs differ from development split")
        attempt_counts = set(counts.values())
        require(len(attempt_counts) == 1 and next(iter(attempt_counts)) >= 3, "baseline dev task attempt counts must match and be K ≥ 3")
        ids = [trace.get("id") for trace in baseline_bundle]
        require(all(isinstance(value, str) and value for value in ids) and len(set(ids)) == len(ids),
                "scored baseline IDs must be nonempty and unique")
        require(all(trace.get("evaluator_results", {}).get("harbor.reward") in (0, 0.0, 1, 1.0) for trace in baseline_bundle),
                "baseline bundle must retain a binary Harbor reward on every trace")
    # When verification is present, its bundle must match the measured run;
    # the original design bundle/report remain the causal candidate inputs.

    measured = json.loads(stage_paths["measured_ab"].read_text(encoding="utf-8"))
    require(measured.get("schema") == "hermes-harbor-ab-comparison-v3", "invalid measured A/B schema")
    attempts = measured.get("attempts_per_task_per_arm")
    require(isinstance(attempts, int) and attempts >= 3, "A/B requires at least three attempts per task and arm")
    fingerprints: set[str] = set()
    for split, cases_on_split in (("development", dev_cases), ("held_out", held_cases)):
        record = measured.get(split, {})
        require(record.get("regressed_tasks") == [], f"{split} has per-task regressions or lacks a regression check")
        require(record.get("tasks") == len(cases_on_split), f"{split} task denominator differs from frozen suite")
        require(record.get("attempts_per_task_per_arm") == attempts, f"{split} attempt count differs")
        for arm in ("baseline", "candidate"):
            summary = record.get(arm, {})
            run = json.loads(stage_paths[f"{arm}_{split}_run"].read_text())
            if split == "held_out":
                for trial in run.get("trials", []):
                    try:
                        started_at = datetime.fromisoformat(trial["started_at"]).astimezone(timezone.utc)
                    except (KeyError, TypeError, ValueError):
                        require(False, "missing or invalid held-out trial start timestamp")
                    require(frozen_at < started_at, "candidate freeze must precede every held-out trial")
            trial_passes, run_fingerprints = validate_run(
                root, run, {case["id"] for case in cases_on_split}, arm, attempts
            )
            if split == "development" and arm == "baseline":
                source_records = {}
                for trial in run["trials"]:
                    task_id = trial["task"].rsplit("/", 1)[-1]
                    for trace_id in trial.get("relay_trajectory_ids", []):
                        require(trace_id not in source_records, "duplicate measured baseline trace ID")
                        source_records[trace_id] = (task_id, trial["reward"])
                bundle_records = {}
                for trace in baseline_bundle:
                    trace_id = trace.get("id")
                    require(isinstance(trace_id, str) and trace_id and trace_id not in bundle_records,
                            "missing or duplicate scored baseline trace ID")
                    bundle_records[trace_id] = (
                        trace["attributes"]["logical_case_id"],
                        trace["evaluator_results"]["harbor.reward"],
                    )
                require(source_records == bundle_records,
                        "scored Insights input differs from measured baseline trace IDs or rewards")
            fingerprints.update(run_fingerprints)
            require(summary.get("passed") == sum(trial_passes.values()), "A/B aggregate differs from Harbor rewards")
            require(all(summary.get("per_task", {}).get(task_id, {}).get("passed") == passed
                        for task_id, passed in trial_passes.items()), "A/B per-task score differs from Harbor rewards")
            require(summary.get("trials") == len(cases_on_split) * attempts, f"{split}/{arm} trial denominator is incomplete")
            require(summary.get("exceptions") == 0, f"{split}/{arm} contains infrastructure exceptions")
            require(set(summary.get("per_task", {})) == {case["id"] for case in cases_on_split},
                    f"{split}/{arm} per-task results differ from the suite")
    require(len(fingerprints) == 1, "model/provider/config/world/policy differs across measured arms or trials")
    require(measured["development"]["candidate_improved"], "candidate must improve development pass rate")
    require(measured["held_out"]["candidate_improved"], "candidate must improve held-out pass rate")
    require(measured.get("acceptance", {}).get("both_splits_improve") is True, "A/B acceptance must record both-split improvement")

    print(
        "artifact chain valid: "
        f"X={len(source_traces)} source traces → Y={len(cases)} tasks "
        f"({len(dev_cases)} development/{len(held_cases)} held out) → "
        f"K={attempts} attempts → candidate improves both splits"
    )
    if not require_review:
        print("Technical pilot integrity only; this does not establish human task review or readiness.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-unreviewed", action="store_true",
                        help="Check technical pilot integrity without claiming human review.")
    args = parser.parse_args()
    validate(ROOT, require_review=not args.allow_unreviewed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
