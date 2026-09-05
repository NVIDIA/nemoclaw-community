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

from bench.fingerprint import fingerprint
from bench.runner import REPO, _git_revision
from bench.grader import grade, is_answered  # noqa: E402
from bench.report import _accounting_method, render_markdown, summarize
from bench.runner import REPORT_SCHEMA_VERSION  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--gold", type=Path, default=REPO / "corpus_a" / "questions" / "answers.jsonl")
    parser.add_argument("--questions", type=Path, default=REPO / "corpus_a" / "questions" / "questions.jsonl")
    parser.add_argument("--corpus", type=Path, default=REPO / "corpus_a" / "corpus",
                        help="only used to fingerprint what the answers were graded against")
    args = parser.parse_args()

    gold = {json.loads(line)["id"]: json.loads(line)
            for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()}
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    answers = {json.loads(line)["id"]: json.loads(line)
               for line in (args.run / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}

    verdicts = [
        grade(q["id"], str(answers.get(q["id"], {}).get("answer", "")),
              answers.get(q["id"], {}).get("source_ids"), gold[q["id"]],
              answered=is_answered(answers.get(q["id"])))
        for q in questions
    ]
    # Two callers, one path. A finished run has a report to re-score in place.
    # Someone who answered the questions by hand has only answers.jsonl -- that
    # is the whole point of the answer-only submission path -- so score that
    # into a fresh report rather than failing on a file they were never told to
    # produce.
    report_path = args.run / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        before = report.get("summary", {}).get("accuracy_overall")
    else:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "adapter": {"name": args.run.name, "revision": None, "declared_model": None},
            "model": None,
            "run_id": args.run.name,
            "fingerprint": fingerprint(args.corpus, args.questions, args.gold),
            "accounting": {
                "method": "not-measured",
                "description": "answers were scored without the harness, so no token cost was observed",
            },
            "timing": {},
            "cost": {},
        }
        manifest_path = args.corpus / "manifest.jsonl"
        if manifest_path.exists():
            manifest = [json.loads(line) for line in
                        manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            report["corpus"] = {
                "documents": len(manifest),
                "part_a": sum(1 for m in manifest if m.get("part") == "part_a"),
                "part_b": sum(1 for m in manifest if m.get("part") == "part_b"),
            }
        else:
            report["corpus"] = {"documents": 0, "part_a": 0, "part_b": 0}
        before = None
    report["summary"] = summarize(verdicts, gold)
    # The fingerprint is the report's claim about what it was graded against.
    # Regrading against a different question set or answer key changes that
    # claim, so it is recomputed here rather than carried over.
    report["fingerprint"] = fingerprint(args.corpus, args.questions, args.gold)
    # The verdicts in this report were produced by the benchmark running now,
    # not by whatever produced the original, so the revision must move with
    # them. Leaving the old one made the report name a scorer that did not
    # score it.
    report["benchmark_revision"] = _git_revision(REPO)
    report["answers_missing"] = [q["id"] for q in questions if not is_answered(answers.get(q["id"]))]
    # Regrading re-decides every verdict, so it re-decides validity with them.
    # Carrying the old flags forward made a corrected submission keep claiming
    # it was invalid for an omission it no longer had. An accounting failure is
    # a property of the original run, not of this scoring pass, so it stays.
    accounting_method = _accounting_method(report)
    accounting_failure = accounting_method in {
        "partial", "declared-proxy-but-silent", "declared-local-but-called",
    }
    report.pop("valid", None)
    report.pop("invalid_reason", None)
    if report["answers_missing"]:
        report["valid"] = False
        report["invalid_reason"] = (
            f"{len(report['answers_missing'])} of {len(questions)} questions received no "
            "answer. An incomplete submission is not a lower score."
        )
    elif accounting_failure:
        report["valid"] = False
        report["invalid_reason"] = (
            "the original run's cost was not fully observed "
            f"({accounting_method}); regrading does not change that."
        )
    # `provenance_note.effect` compares two gradings of the same run, so it is
    # only true of the grader that produced it. Leaving it behind on a regrade
    # published a comparison against a scorer that no longer exists; recompute
    # both halves from the two answer files whenever the untransformed one ships.
    as_answered = args.run / "answers.as-answered.jsonl"
    effect = report.get("provenance_note", {}).get("effect")
    if effect is not None and as_answered.exists():
        raw = {json.loads(line)["id"]: json.loads(line)
               for line in as_answered.read_text(encoding="utf-8").splitlines() if line.strip()}
        raw_verdicts = [
            grade(q["id"], str(raw.get(q["id"], {}).get("answer", "")),
                  raw.get(q["id"], {}).get("source_ids"), gold[q["id"]],
                  answered=is_answered(raw.get(q["id"])))
            for q in questions
        ]
        effect["accuracy_as_answered"] = summarize(raw_verdicts, gold)["accuracy_overall"]
        effect["accuracy_after_map"] = report["summary"]["accuracy_overall"]
        effect["questions_reported_unanswered_before_id_map"] = sum(
            1 for q in questions if not is_answered(raw.get(q["id"])))

    report["regraded"] = True
    (args.run / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.run / "verdicts.jsonl").write_text(
        "\n".join(json.dumps(v.to_dict()) for v in verdicts) + "\n", encoding="utf-8")
    (args.run / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    now = report["summary"]["accuracy_overall"]
    moved = f"{before} -> {now}" if before is not None else f"{now}"
    print(f"{args.run.name}: accuracy {moved}")
    print(f"wrote {report_path.name}, verdicts.jsonl and summary.md to {args.run}")


if __name__ == "__main__":
    main()
