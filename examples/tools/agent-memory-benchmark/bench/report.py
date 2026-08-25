# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turn per-question verdicts into the numbers a leaderboard row carries."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from bench.grader import Verdict


def summarize(verdicts: Iterable[Verdict], gold_by_id: dict[str, dict]) -> dict:
    """Aggregate accuracy by question type plus the evidence diagnostics.

    Questions deferred to a judge model are counted separately (no shipped question is: the count is always zero) rather than
    folded into accuracy, so a run that skipped judging cannot look better than
    one that ran it.
    """
    verdicts = list(verdicts)
    by_type: dict[str, list[Verdict]] = defaultdict(list)
    for verdict in verdicts:
        by_type[gold_by_id[verdict.question_id].get("type", "unknown")].append(verdict)

    def rate(items: list[Verdict]) -> float | None:
        graded = [v for v in items if v.correct is not None]
        return round(sum(1 for v in graded if v.correct) / len(graded), 4) if graded else None

    recalls = [v.evidence_recall for v in verdicts if v.evidence_recall is not None]
    precisions = [v.evidence_precision for v in verdicts if v.evidence_precision is not None]
    cited_any = sum(1 for v in verdicts if v.cited)

    freshness_split: dict[str, float | None] = {}
    for label, want in (("with_stale_in_corpus", True), ("recency_only", False)):
        subset = [
            v for v in by_type.get("freshness", [])
            if bool(gold_by_id[v.question_id].get("stale_in_corpus")) is want
        ]
        freshness_split[label] = rate(subset)

    by_difficulty: dict[str, list[Verdict]] = defaultdict(list)
    for verdict in verdicts:
        by_difficulty[gold_by_id[verdict.question_id].get("difficulty", "base")].append(verdict)

    return {
        "questions": len(verdicts),
        "graded": sum(1 for v in verdicts if v.correct is not None),
        "deferred_to_judge": sum(1 for v in verdicts if v.needs_llm),
        "accuracy_overall": rate(verdicts),
        "accuracy_by_type": {name: rate(items) for name, items in sorted(by_type.items())},
        "accuracy_by_difficulty": {name: rate(items) for name, items in sorted(by_difficulty.items())},
        "freshness_detail": freshness_split,
        "evidence": {
            "questions_with_citations": cited_any,
            "citation_coverage": round(cited_any / len(verdicts), 4) if verdicts else None,
            "evidence_recall_mean": round(sum(recalls) / len(recalls), 4) if recalls else None,
            "evidence_precision_mean": round(sum(precisions) / len(precisions), 4) if precisions else None,
        },
    }


def _adapter_name(report: dict) -> str:
    """Adapter name across report schema versions.

    Schema 1 made ``adapter`` an object so a row could carry the revision that
    produced it; before that it was the bare name. Stored reports are not
    rewritten, so both shapes render.
    """
    adapter = report.get("adapter")
    if isinstance(adapter, dict):
        return str(adapter.get("name", "unnamed"))
    return str(adapter or "unnamed")


def _accounting_method(report: dict) -> str:
    accounting = report.get("accounting", "proxy")
    if isinstance(accounting, dict):
        return str(accounting.get("method", "unknown"))
    return str(accounting)


def render_markdown(report: dict) -> str:
    """One human-readable block per run — the thing pasted into an issue or MR."""
    summary = report["summary"]
    cost = report.get("cost", {})
    lines = [
        f"# {_adapter_name(report)} — {report.get('model') or 'model not declared'}",
        "",
        f"* corpus: {report['corpus']['documents']} docs "
        f"({report['corpus']['part_a']} part_a / {report['corpus']['part_b']} part_b)",
        f"* questions: {summary['questions']} "
        f"(graded deterministically: {summary['graded']}, deferred to judge: {summary['deferred_to_judge']})",
        "",
        "## Quality",
        f"* accuracy overall: **{summary['accuracy_overall']}**",
    ]
    for name, value in summary.get("accuracy_by_difficulty", {}).items():
        lines.append(f"  * [{name}] {value}")
    for name, value in summary["accuracy_by_type"].items():
        lines.append(f"  * {name}: {value}")
    detail = summary["freshness_detail"]
    lines += [
        f"  * freshness with a competing stale claim in corpus: {detail['with_stale_in_corpus']}",
        f"  * freshness recency-only: {detail['recency_only']}",
        "",
        "## Evidence (diagnostic, not part of accuracy)",
        f"* citation coverage: {summary['evidence']['citation_coverage']}",
        f"* evidence recall: {summary['evidence']['evidence_recall_mean']}",
        f"* evidence precision: {summary['evidence']['evidence_precision_mean']}",
        "",
        "## Cost",
        f"* ingest: {cost.get('ingest_input_tokens', 0)} in / {cost.get('ingest_output_tokens', 0)} out "
        f"in {report['timing'].get('ingest_seconds')}s",
        f"* answering: {cost.get('answer_input_tokens', 0)} in / {cost.get('answer_output_tokens', 0)} out "
        f"in {report['timing'].get('answer_seconds')}s",
        f"* per question: {cost.get('tokens_per_question')} tokens",
        f"* accounting: {_accounting_method(report)}",
    ]
    self_reported = report.get("self_reported_usage")
    if self_reported:
        latest = self_reported["latest"]
        lines.append(
            f"* system's own counter (spans resumed segments the proxy did not supervise): "
            f"{latest.get('input_tokens', 0):,} in / {latest.get('output_tokens', 0):,} out "
            f"over {latest.get('calls', 0)} calls"
        )
    if cost.get("ingest_usd") is not None:
        lines.append(f"* USD (price snapshot {cost.get('price_snapshot')}): "
                     f"ingest ${cost['ingest_usd']}, answering ${cost['answer_usd']}")
    return "\n".join(lines) + "\n"
