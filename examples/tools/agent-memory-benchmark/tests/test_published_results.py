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
def test_the_published_map_reproduces_the_transformed_answers(run: Path):
    """Apply the published map to the as-answered rows and expect answers.jsonl.

    The claim is that the same substitution applied to the corpus was applied
    to the answers and nothing else was changed. An earlier version of this
    test only checked that a non-empty map existed, which proves nothing: it
    would pass against a map that was wrong, abbreviated, or unrelated to the
    file beside it.
    """
    note = _report(run)["provenance_note"]
    text_map = note["substitutions"]["text"]
    id_map = note["substitutions"]["question_ids"]
    assert text_map and id_map, "the map must ship whole, not summarised"
    assert not any("..." in k or "full map" in k.lower() for k in text_map), (
        "the published map must be the map, not a pointer to one"
    )

    def rows(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    rebuilt = []
    for row in rows(run / "answers.as-answered.jsonl"):
        out = dict(row)
        out["id"] = id_map.get(row["id"], row["id"])
        answer = str(row.get("answer", ""))
        for old_text, new_text in text_map.items():
            answer = answer.replace(old_text, new_text)
        if "answer" in row:
            out["answer"] = answer
        rebuilt.append(out)

    published = rows(run / "answers.jsonl")
    assert len(rebuilt) == len(published)
    mismatches = [(a["id"], b["id"]) for a, b in zip(rebuilt, published) if a != b]
    assert not mismatches, (
        f"{run.name}: applying the published map to answers.as-answered.jsonl does not "
        f"reproduce answers.jsonl; {len(mismatches)} rows differ, first {mismatches[:3]}"
    )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_transform_changed_only_what_the_map_touches(run: Path):
    """Nothing outside the map moved: every difference is explained by it."""
    def rows(path: Path) -> dict:
        return {json.loads(l)["id"]: json.loads(l)
                for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    note = _report(run)["provenance_note"]
    id_map = note["substitutions"]["question_ids"]
    text_map = note["substitutions"]["text"]
    before, after = rows(run / "answers.as-answered.jsonl"), rows(run / "answers.jsonl")
    for old_id, row in before.items():
        new_id = id_map.get(old_id, old_id)
        assert new_id in after, f"{old_id} vanished from the transformed answers"
        old_answer, new_answer = str(row.get("answer", "")), str(after[new_id].get("answer", ""))
        if old_answer == new_answer:
            continue
        assert any(k in old_answer for k in text_map), (
            f"{new_id} changed but contains no key from the published map"
        )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_report_follows_the_current_schema(run: Path):
    """A published example must be an example of the current output format."""
    r = _report(run)
    assert r.get("schema_version") == 1, "reports must carry the current schema version"
    adapter = r.get("adapter")
    assert isinstance(adapter, dict) and adapter.get("name"), "adapter must be structured"
    assert "revision" in adapter and "declared_model" in adapter
    assert r.get("trial") == {"index": 1, "of": 1}
    assert "run_parameters" in r, "the parameters a rerun would need must be recorded"
    accounting = r.get("accounting")
    assert isinstance(accounting, dict), "accounting must be the structured record, not a bare string"
    for key in ("declared", "method", "forwarded_calls", "uncounted_calls", "comparable_on_cost"):
        assert key in accounting, f"accounting is missing {key}"


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_transform_is_disclosed(run: Path):
    note = _report(run).get("provenance_note")
    assert note and note.get("answers_transformed") is True
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


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_the_published_effect_is_what_regrading_actually_gives(run: Path, tmp_path):
    """`effect` is a claim about two numbers; recompute both and compare.

    These values described a previous grader for one round, because the grader
    moved and the report did not. Deriving them here means they cannot drift
    again without a test failing.
    """
    note = _report(run)["provenance_note"]["effect"]

    def score(source: Path) -> float:
        scratch = tmp_path / source.stem
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "answers.jsonl").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "tools/regrade.py", "--run", str(scratch)],
            cwd=REPO, capture_output=True, text=True, timeout=180)
        assert completed.returncode == 0, completed.stderr[-1500:]
        return json.loads((scratch / "report.json").read_text())["summary"]["accuracy_overall"]

    assert score(run / "answers.as-answered.jsonl") == pytest.approx(note["accuracy_as_answered"]), (
        "provenance_note.effect.accuracy_as_answered is not what regrading gives"
    )
    assert score(run / "answers.jsonl") == pytest.approx(note["accuracy_after_map"]), (
        "provenance_note.effect.accuracy_after_map is not what regrading gives"
    )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_accounting_claims_only_what_the_artifact_establishes(run: Path):
    """A count the stored run never recorded must read as unknown, not as zero.

    These runs predate the forwarded-call record, so the gap between forwarded
    and counted calls cannot be derived from them. Asserting `uncounted: 0` and
    `comparable_on_cost: true` would be inventing the evidence for a cost
    comparison.
    """
    r = _report(run)
    accounting = r["accounting"]
    observed = accounting.get("observed_calls") or {}
    assert observed == r.get("usage_raw", {}).get("calls", {}), (
        "the reported call counts must be the ones the run recorded, ingest included"
    )
    assert accounting["observed_calls_total"] == sum(observed.values())
    assert accounting["forwarded_calls"] is None
    assert accounting["uncounted_calls"] is None
    assert accounting["comparable_on_cost"] is False, (
        "a run whose forwarded calls were never recorded cannot be compared on cost"
    )


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_adapter_provenance_says_what_is_and_is_not_reproducible(run: Path):
    revision = _report(run)["adapter"]["revision"]
    assert "note" in revision and revision["note"], "adapter provenance must say something"
    if run.name.startswith("agentic-rag"):
        assert revision["shipped_here"] == "adapters/agentic_rag"
        assert _report(run)["run_parameters"]["max_rounds"] == 3
        # An adapter that ships here can be identified exactly, so it is.
        from bench.fingerprint import hash_tree

        assert revision["files_sha256"] == hash_tree(REPO / "adapters" / "agentic_rag"), (
            "the recorded adapter hash does not match the adapter that ships; if the "
            "adapter changed, the published run no longer describes it"
        )
        assert revision["shared_lib_sha256"] == hash_tree(REPO / "adapters" / "_lib")
    else:
        assert revision["shipped_here"] is None
        assert "not reproducible" in revision["note"]


# A ratio between the two cost columns is a comparison, and these runs have not
# earned one: neither report carries a forwarded-call record, so both set
# `comparable_on_cost` to false. The prose said "1,076 times more" two lines
# below the sentence admitting the counts were unproven. This keeps the prose
# and the flag from disagreeing again.
_COST_RATIO = re.compile(
    r"\b\d[\d,.]*\s*(?:times|x|×)\s+(?:more|less|fewer|cheaper|costlier|higher|lower|the|as)\b"
    r"|\b(?:more|less)\s+than\s+\d[\d,.]*\s*(?:times|x|×)\b"
    r"|\border[s]? of magnitude\b",
    re.IGNORECASE)


def _published_prose() -> list[Path]:
    results = REPO / "results"
    return [results / "README.md", *sorted((results / "runs").glob("*/summary.md"))]


def test_published_prose_states_no_cost_ratio_while_cost_is_not_comparable():
    """No comparative cost claim may ship while a run says it cannot support one."""
    unproven = sorted(
        run.name for run in RUNS
        if not _report(run)["accounting"].get("comparable_on_cost"))
    if not unproven:
        return  # every shipped run established its accounting; a ratio is earned
    for doc in _published_prose():
        for number, line in enumerate(doc.read_text().splitlines(), 1):
            found = _COST_RATIO.search(line)
            assert not found, (
                f"{doc.relative_to(REPO)}:{number} states the cost ratio "
                f"{found.group(0)!r}, but {', '.join(unproven)} set "
                f"comparable_on_cost to false. Report each run's observed counts, "
                f"or establish the accounting and flip the flag.")
