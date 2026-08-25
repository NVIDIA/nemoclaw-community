#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Re-grade a finished run against the current answer key.

Grading rules get fixed — a normalization gap, a reject phrase that also matched
a correct refusal. When they do, every past run should be recomputed rather than
re-executed: the answers are already on disk, and re-running would cost money and
change what is being compared. This rewrites ``report.json``, ``verdicts.jsonl``
and ``summary.md`` in place from the stored ``answers.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.grader import grade  # noqa: E402
from bench.report import render_markdown, summarize  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--gold", type=Path, default=REPO / "gold" / "answers.jsonl")
    parser.add_argument("--questions", type=Path, default=REPO / "questions" / "questions.jsonl")
    args = parser.parse_args()

    gold = {json.loads(line)["id"]: json.loads(line)
            for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()}
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    answers = {json.loads(line)["id"]: json.loads(line)
               for line in (args.run / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}

    verdicts = [
        grade(q["id"], str(answers.get(q["id"], {}).get("answer", "")),
              answers.get(q["id"], {}).get("source_ids"), gold[q["id"]])
        for q in questions
    ]
    report = json.loads((args.run / "report.json").read_text(encoding="utf-8"))
    before = report["summary"]["accuracy_overall"]
    report["summary"] = summarize(verdicts, gold)
    report["regraded"] = True
    (args.run / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.run / "verdicts.jsonl").write_text(
        "\n".join(json.dumps(v.to_dict()) for v in verdicts) + "\n", encoding="utf-8")
    (args.run / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"{args.run.name}: accuracy {before} -> {report['summary']['accuracy_overall']}")


if __name__ == "__main__":
    main()
