#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compare two runs on exactly the questions both of them answered.

A long run can be cut short, and a partial answer file is still a valid
measurement — as long as the other system is scored on the same questions. This
grades both runs over the intersection of their answered ids and prints the
comparison, rather than letting a truncated run be compared against a full one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.grader import grade  # noqa: E402
from bench.report import summarize  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _answers(run: Path) -> dict[str, dict]:
    path = run / "answers.jsonl"
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("id"):
            rows[row["id"]] = row
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, type=Path)
    parser.add_argument("--gold", type=Path, default=REPO / "gold" / "answers.jsonl")
    parser.add_argument("--out", type=Path, default=REPO / "results" / "comparison.md")
    args = parser.parse_args()

    gold = {json.loads(line)["id"]: json.loads(line)
            for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()}
    per_run = {run.name: _answers(run) for run in args.runs}
    shared = set.intersection(*(set(rows) for rows in per_run.values()))
    if not shared:
        raise SystemExit("the runs share no answered questions")

    summaries = {}
    for name, rows in per_run.items():
        verdicts = [
            grade(qid, str(rows[qid].get("answer", "")), rows[qid].get("source_ids"), gold[qid])
            for qid in sorted(shared)
        ]
        summaries[name] = summarize(verdicts, gold)

    types = sorted({gold[q]["type"] for q in shared})
    names = list(summaries)
    header = "| metric | " + " | ".join(names) + " |"
    lines = [
        f"# Comparison over {len(shared)} shared questions",
        "",
        "Both systems graded on exactly the questions both answered.",
        "",
        "| type | count |",
        "|---|---:|",
    ]
    for qtype in types:
        lines.append(f"| {qtype} | {sum(1 for q in shared if gold[q]['type'] == qtype)} |")
    lines += ["", header, "|---" * (len(names) + 1) + "|",
              "| accuracy | " + " | ".join(str(summaries[n]["accuracy_overall"]) for n in names) + " |"]
    for qtype in types:
        lines.append(f"| {qtype} | " + " | ".join(
            str(summaries[n]["accuracy_by_type"].get(qtype)) for n in names) + " |")
    lines.append("| evidence recall | " + " | ".join(
        str(summaries[n]["evidence"]["evidence_recall_mean"]) for n in names) + " |")
    lines.append("| citation coverage | " + " | ".join(
        str(summaries[n]["evidence"]["citation_coverage"]) for n in names) + " |")
    text = "\n".join(lines) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
