#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render every completed run as a leaderboard, grouped by base model.

Rows are grouped rather than globally ranked: the same memory architecture on
two different models can differ more than two architectures on the same one, so
a single ordering across models would be misleading.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _adapter_name(report: dict) -> str:
    """Adapter name across report schema versions.

    Schema 1 made ``adapter`` an object so a row could carry the revision that
    produced it; before that it was the bare name. Stored runs are not
    rewritten, so both shapes are read here.
    """
    adapter = report.get("adapter")
    if isinstance(adapter, dict):
        return str(adapter.get("name", ""))
    return str(adapter or "")


def _accounting_method(report: dict) -> str:
    """Token-count method across report schema versions."""
    accounting = report.get("accounting", "")
    if isinstance(accounting, dict):
        return str(accounting.get("method", ""))
    return str(accounting)


def _rows(runs_dir: Path) -> list[dict]:
    rows = []
    for report_path in sorted(runs_dir.glob("*/report.json")):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # A run can be invalidated after the fact — a harness bug that made the
        # measurement mean something other than intended. Those stay on disk
        # with their reason and are listed below the table, never ranked in it.
        if report.get("valid") is False:
            rows.append({"invalid": True, "run_id": report_path.parent.name,
                         "adapter": _adapter_name(report), "reason": report.get("invalid_reason", "")})
            continue
        summary, cost = report["summary"], report.get("cost", {})
        rows.append(
            {
                "adapter": _adapter_name(report),
                "model": report.get("model") or "undeclared",
                "accuracy": summary["accuracy_overall"],
                "by_type": summary["accuracy_by_type"],
                "abstention": summary["accuracy_by_type"].get("abstention"),
                "ingest_tokens": cost.get("ingest_input_tokens", 0) + cost.get("ingest_output_tokens", 0),
                "per_question_tokens": cost.get("tokens_per_question"),
                "evidence_recall": summary["evidence"]["evidence_recall_mean"],
                "accounting": _accounting_method(report),
                "corpus": report.get("corpus", "A"),
                "run_id": report.get("run_id", report_path.parent.name),
            }
        )
    return rows


def _breakeven(a: dict, b: dict) -> str:
    """At how many questions does the heavier ingest pay for itself?"""
    heavy, light = (a, b) if a["ingest_tokens"] >= b["ingest_tokens"] else (b, a)
    per_gap = (light["per_question_tokens"] or 0) - (heavy["per_question_tokens"] or 0)
    if per_gap <= 0:
        return (f"{heavy['adapter']} costs more at ingest *and* per question — "
                f"no crossover; {light['adapter']} is cheaper at every N.")
    n = (heavy["ingest_tokens"] - light["ingest_tokens"]) / per_gap
    return (f"{heavy['adapter']} overtakes {light['adapter']} on total tokens at "
            f"**N ≈ {n:,.0f} questions** "
            f"(ingest gap {heavy['ingest_tokens'] - light['ingest_tokens']:,.0f} tokens ÷ "
            f"per-question saving {per_gap:,.0f}).")


def render(rows: list[dict]) -> str:
    lines = ["# Leaderboard", ""]
    valid = [r for r in rows if not r.get("invalid")]
    invalid = [r for r in rows if r.get("invalid")]
    by_group: dict[tuple[str, str], list[dict]] = {}
    for row in valid:
        by_group.setdefault((row["corpus"], row["model"]), []).append(row)
    for (corpus, model), group in sorted(by_group.items()):
        lines += [f"## Corpus {corpus} — {model}", "",
                  "| system | accuracy | abstention | evidence recall | ingest tokens | tokens/question | accounting |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for row in sorted(group, key=lambda r: -(r["accuracy"] or 0)):
            lines.append(
                f"| {row['adapter']} | {row['accuracy']} | {row['abstention']} | {row['evidence_recall']} | "
                f"{row['ingest_tokens']:,} | {row['per_question_tokens']} | {row['accounting']} |"
            )
        lines.append("")
        if len(group) == 2:
            lines += ["**Ingest-time vs query-time:** " + _breakeven(*group), ""]
    if invalid:
        lines += ["## Voided runs", "",
                  "Kept on disk with their answers and verdicts; excluded from the table.", ""]
        for row in invalid:
            lines.append(f"* `{row['run_id']}` ({row['adapter']}) — {row['reason']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=REPO / "results" / "runs")
    parser.add_argument("--out", type=Path, default=REPO / "results" / "leaderboard.md")
    args = parser.parse_args()
    rows = _rows(args.runs)
    text = render(rows)
    args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
