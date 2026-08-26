# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The shipped reference results must stay true to what ships beside them.

A published number is a claim about the corpus, the questions, the answer key
and the grader in this repository. All four move; the numbers do not move with
them unless something fails. These tests are that something.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNS = sorted((REPO / "results" / "runs").iterdir()) if (REPO / "results" / "runs").exists() else []
sys.path.insert(0, str(REPO))

from bench.fingerprint import fingerprint  # noqa: E402


def _report(run: Path) -> dict:
    return json.loads((run / "report.json").read_text(encoding="utf-8"))


def test_reference_results_ship():
    assert RUNS, "results/runs/ is empty; the reference results did not ship"


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_every_run_carries_the_four_artifacts(run: Path):
    for name in ("report.json", "answers.jsonl", "verdicts.jsonl", "summary.md"):
        assert (run / name).exists(), f"{run.name} is missing {name}"
    assert (run / "answers.as-answered.jsonl").exists(), (
        f"{run.name} must ship the untransformed answers so the rename can be checked"
    )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_fingerprint_matches_what_ships_today(run: Path):
    """A stored result graded against a corpus that has since changed is not a
    result about this repository."""
    current = fingerprint(REPO / "corpus", REPO / "questions" / "questions.jsonl",
                          REPO / "gold" / "answers.jsonl")
    stored = _report(run).get("fingerprint")
    assert stored, f"{run.name} has no fingerprint"
    for key in ("corpus", "questions", "gold", "scorer", "normalization"):
        assert stored[key] == current[key], (
            f"{run.name}: {key} no longer matches. Regrade the stored answers and "
            f"update results/README.md, or the published number describes something "
            f"that is not here any more."
        )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_published_score_reproduces_from_the_stored_answers(run: Path, tmp_path):
    """Re-score the shipped answers and expect the shipped number back."""
    scratch = tmp_path / run.name
    scratch.mkdir()
    (scratch / "answers.jsonl").write_text(
        (run / "answers.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/regrade.py", "--run", str(scratch)],
        cwd=REPO, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr[-1500:]
    fresh = json.loads((scratch / "report.json").read_text(encoding="utf-8"))
    assert fresh["summary"] == _report(run)["summary"], (
        f"{run.name}: re-scoring the shipped answers does not give the shipped summary"
    )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_every_run_is_valid(run: Path):
    report = _report(run)
    assert report.get("valid") is not False, report.get("invalid_reason")
    assert not report.get("answers_missing")


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_transform_is_disclosed(run: Path):
    note = _report(run).get("provenance_note")
    assert note and note.get("answers_transformed") is True
    assert note.get("substitutions"), "the substitution map must ship with the claim"
    assert "not a run against the published corpus" in note["not_a_rerun"]


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_readme_states_this_run_s_headline(run: Path):
    """The table a reader sees must be the number the report carries."""
    readme = (REPO / "results" / "README.md").read_text(encoding="utf-8")
    overall = _report(run)["summary"]["accuracy_overall"]
    assert f"{overall:.1%}" in readme, (
        f"{run.name} scores {overall:.1%}, which does not appear in results/README.md"
    )


def test_the_readme_says_corpus_a_only():
    readme = (REPO / "results" / "README.md").read_text(encoding="utf-8")
    assert "Corpus A only" in readme or "corpus A only" in readme
    assert "One base model" in readme, (
        "the methodology asks for two; the omission must be stated where the numbers are"
    )
