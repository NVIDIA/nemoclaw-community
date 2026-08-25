# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What gets rendered for a reader, tested on the paths that produce gaps.

Two of these were shipped defects: a raw Python dict in the summary heading,
and a column of raw ``None`` in a file the submission guide tells contributors
to read. Both came from a value that exists in one code path and not another,
which is exactly what these tests hold still.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
sys.path.insert(0, str(REPO))

from bench.report import render_markdown  # noqa: E402


def _answers_only_run(tmp_path: Path) -> Path:
    """A directory holding answers and nothing else — the answer-only path."""
    run = tmp_path / "run"
    run.mkdir()
    ids = [json.loads(line)["id"] for line in
           (SELFTEST / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    run.joinpath("answers.jsonl").write_text(
        "\n".join(json.dumps({"id": i, "answer": "60%"}) for i in ids) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/regrade.py", "--run", str(run),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--corpus", str(SELFTEST / "corpus")],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-1500:]
    return run


def test_scoring_answers_alone_needs_no_report_to_start_from(tmp_path):
    run = _answers_only_run(tmp_path)
    for name in ("report.json", "verdicts.jsonl", "summary.md"):
        assert (run / name).exists(), f"{name} was not written"


def test_the_summary_never_renders_a_raw_python_value(tmp_path):
    summary = (_answers_only_run(tmp_path) / "summary.md").read_text(encoding="utf-8")
    for leak in ("None", "{'", '{"name"', "dict_"):
        assert leak not in summary, f"{leak!r} rendered into summary.md:\n{summary}"


def test_the_summary_heading_names_the_adapter(tmp_path):
    summary = (_answers_only_run(tmp_path) / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("# run "), summary.splitlines()[0]


def test_a_rate_that_was_never_computed_says_so_rather_than_zero():
    report = {
        "adapter": {"name": "x"}, "model": None, "timing": {}, "cost": {},
        "accounting": {"method": "not-measured"},
        "summary": {
            "questions": 1, "graded": 1, "deferred_to_judge": 0, "accuracy_overall": 1.0,
            "accuracy_by_type": {"freshness": 1.0}, "accuracy_by_difficulty": {"base": 1.0},
            "freshness_detail": {"with_stale_in_corpus": None, "recency_only": None},
            "evidence": {"questions_with_citations": 0, "citation_coverage": 0.0,
                         "evidence_recall_mean": None, "evidence_precision_mean": None},
        },
        "corpus": {"documents": 1, "part_a": 1, "part_b": 0},
    }
    rendered = render_markdown(report)
    assert "None" not in rendered
    assert "n/a" in rendered
    assert "0.0" != rendered, "an uncomputed rate must not be rendered as zero"
