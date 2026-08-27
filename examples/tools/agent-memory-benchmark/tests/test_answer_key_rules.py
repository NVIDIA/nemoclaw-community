# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Invariants of the shipped question set and answer key.

The grading rules are the benchmark's contract. A duplicate id, a string that
is both accepted and rejected, or a gold citation pointing at a document that
was renamed would each change scores silently, so each is a test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bench.fingerprint import fingerprint  # noqa: E402
from bench.grader import grade, normalize  # noqa: E402

VALID_MODES = {"string_any", "boolean", "abstain", "ordering"}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


QUESTIONS = _rows(REPO / "corpus_a" / "questions" / "questions.jsonl")
GOLD = _rows(REPO / "corpus_a" / "questions" / "answers.jsonl")
MANIFEST = _rows(REPO / "corpus_a" / "corpus" / "manifest.jsonl")
DOC_IDS = {row["doc_id"] for row in MANIFEST}


def test_question_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate question ids: {duplicates}"


def test_gold_ids_are_unique_and_match_the_questions_exactly():
    gold_ids = [g["id"] for g in GOLD]
    assert len(gold_ids) == len(set(gold_ids)), "duplicate ids in the answer key"
    assert set(gold_ids) == {q["id"] for q in QUESTIONS}, (
        "the question set and the answer key disagree about which questions exist"
    )


def test_every_grading_mode_is_one_the_grader_implements():
    unknown = {g.get("mode", "string_any") for g in GOLD} - VALID_MODES
    assert not unknown, f"answer key uses modes the grader does not implement: {unknown}"


def test_no_string_is_both_accepted_and_rejected():
    """A value on both lists makes the verdict depend on evaluation order."""
    clashes = []
    for g in GOLD:
        accept = {normalize(str(a)) for a in g.get("accept", [])}
        reject = {normalize(str(r)) for r in g.get("reject", [])}
        both = accept & reject
        if both:
            clashes.append((g["id"], sorted(both)))
    assert not clashes, f"accept and reject overlap: {clashes}"


def test_a_rejected_string_is_never_required():
    clashes = []
    for g in GOLD:
        required = {normalize(str(r)) for r in g.get("require_all", [])}
        reject = {normalize(str(r)) for r in g.get("reject", [])}
        both = required & reject
        if both:
            clashes.append((g["id"], sorted(both)))
    assert not clashes, f"require_all demands a string reject forbids: {clashes}"


def test_every_gold_citation_points_at_a_document_that_exists():
    dangling = []
    for g in GOLD:
        for source_id in g.get("gold_source_ids", []) or []:
            if source_id not in DOC_IDS:
                dangling.append((g["id"], source_id))
    assert not dangling, f"gold_source_ids that no manifest entry matches: {dangling}"


def test_each_mode_carries_the_fields_its_handler_reads():
    problems = []
    for g in GOLD:
        mode = g.get("mode", "string_any")
        if mode == "string_any" and not (g.get("accept") or g.get("require_all")):
            problems.append((g["id"], "string_any with neither accept nor require_all"))
        if mode == "boolean" and str(g.get("expected", "")).lower() not in {"yes", "no"}:
            problems.append((g["id"], f"boolean expected={g.get('expected')!r}"))
        if mode == "ordering" and len(g.get("sequence", [])) < 2:
            problems.append((g["id"], "ordering needs at least two elements"))
    assert not problems, problems


def test_abstention_items_have_no_accepted_answer():
    """There is no right answer to give; only declining is right."""
    offenders = [g["id"] for g in GOLD if g.get("mode") == "abstain" and g.get("accept")]
    assert not offenders, f"abstention items must not carry accept: {offenders}"


def test_every_declared_question_type_is_actually_present():
    declared = {q["type"] for q in QUESTIONS}
    counts = {t: sum(1 for q in QUESTIONS if q["type"] == t) for t in declared}
    assert all(n > 0 for n in counts.values())
    assert {"abstention", "freshness", "multi_source", "single_hop"} <= declared, (
        f"a core question type disappeared from the set: {sorted(declared)}"
    )


def test_the_difficulty_split_is_what_the_documentation_claims():
    counts = {d: sum(1 for q in QUESTIONS if q["difficulty"] == d) for d in {"base", "hard"}}
    assert counts == {"base": 155, "hard": 31}, (
        f"README and docs/methodology.md both state 155 base + 31 hard; found {counts}"
    )


@pytest.mark.parametrize("question_id", [g["id"] for g in GOLD[:40]])
def test_grading_the_same_answer_twice_gives_the_same_verdict(question_id):
    gold = next(g for g in GOLD if g["id"] == question_id)
    probe = "60% and 2026-07-14 and the shared cache"
    first = grade(question_id, probe, ["E:nope"], gold)
    second = grade(question_id, probe, ["E:nope"], gold)
    assert first.to_dict() == second.to_dict()


def test_the_fingerprint_is_stable_across_calls():
    a = fingerprint(REPO / "corpus_a" / "corpus", REPO / "corpus_a" / "questions" / "questions.jsonl", REPO / "corpus_a" / "questions" / "answers.jsonl")
    b = fingerprint(REPO / "corpus_a" / "corpus", REPO / "corpus_a" / "questions" / "questions.jsonl", REPO / "corpus_a" / "questions" / "answers.jsonl")
    assert a == b


def test_the_published_hashes_still_describe_what_ships():
    """docs/provenance.md states hashes; a corpus edit must update them.

    Without this, the provenance table is a claim nobody re-checks, and the
    first person to fix a typo in a document silently invalidates it.
    """
    import re

    from bench.fingerprint import hash_file, hash_tree

    published = dict(
        re.findall(r"\| `([^`]+)`[^|]*\|[^|]*\|\s*`([0-9a-f]{64})`", (REPO / "docs" / "provenance.md").read_text())
    )
    assert published, "no hash table found in docs/provenance.md"
    computed = {
        "corpus_a/corpus/": hash_tree(REPO / "corpus_a" / "corpus"),
        "corpus_b/corpus/": hash_tree(REPO / "corpus_b" / "corpus"),
        "corpus_a/questions/questions.jsonl": hash_file(REPO / "corpus_a" / "questions" / "questions.jsonl"),
        "corpus_a/questions/answers.jsonl": hash_file(REPO / "corpus_a" / "questions" / "answers.jsonl"),
        "corpus_b/questions/questions.jsonl": hash_file(REPO / "corpus_b" / "questions" / "questions.jsonl"),
        "corpus_b/questions/answers.jsonl": hash_file(REPO / "corpus_b" / "questions" / "answers.jsonl"),
    }
    stale = {k: (published.get(k), v) for k, v in computed.items() if published.get(k) != v}
    assert not stale, (
        "docs/provenance.md is out of date; recompute the table. "
        f"published vs computed: {stale}"
    )


def test_no_address_in_either_corpus_uses_a_registrable_domain():
    """RFC 2606 reserves .example; an ordinary .com can be owned by anyone."""
    import re

    pattern = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
    offenders: set[str] = set()
    for root in (REPO / "corpus_a" / "corpus", REPO / "corpus_b" / "corpus"):
        for path in root.rglob("*.md"):
            for domain in pattern.findall(path.read_text(encoding="utf-8")):
                if not domain.lower().endswith(".example"):
                    offenders.add(domain)
    assert not offenders, f"addresses outside the reserved .example TLD: {sorted(offenders)}"


def test_the_readme_states_the_number_of_tests_that_exist():
    """The count a reader uses to confirm the install must be the real one.

    It has been wrong twice: a round of review added test files and left the
    README's number behind. Pinning it here means the next person who adds a
    test is told to update the sentence.
    """
    import re
    import subprocess
    import sys

    stated = re.search(r"expected: (\d+) passed", (REPO / "README.md").read_text())
    assert stated, "README no longer states an expected test count"
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    ).stdout
    actual = re.search(r"(\d+) tests? collected", collected)
    assert actual, collected[-500:]
    assert int(stated.group(1)) == int(actual.group(1)), (
        f"README says {stated.group(1)} passed; the suite collects {actual.group(1)}"
    )


def test_no_accepted_answer_is_a_bare_common_word():
    """A one-word `accept` makes an answer that contradicts the gold correct.

    `asof-jordan-load` accepted bare "still", so "it was still being worked but
    no longer untouched" -- the opposite of the gold -- scored correct.
    """
    COMMON = {"still", "open", "yes", "no", "done", "not", "none", "some", "was", "is", "the"}
    offenders = []
    for g in GOLD:
        for a in g.get("accept", []):
            if str(a).strip().lower() in COMMON:
                offenders.append((g["id"], a))
    assert not offenders, f"accept entries that match almost any answer: {offenders}"


def test_the_submission_guide_quotes_the_contract_verbatim():
    """The guide's pasted copy is what a Path-1 submitter actually uses.

    The module is importable so an adapter cannot drift, but the copy in the
    document is hand-maintained and nothing held the two together.
    """
    import re

    from bench.answer_contract import ANSWER_CONTRACT

    guide = (REPO / "docs" / "SUBMITTING.md").read_text(encoding="utf-8")
    quoted = re.search(r"```\n(Answer the question from the memory.*?)```", guide, re.S)
    assert quoted, "the submission guide no longer quotes the answer contract"
    assert quoted.group(1).strip() == ANSWER_CONTRACT.strip(), (
        "docs/SUBMITTING.md and bench/answer_contract.py have drifted apart"
    )


def test_the_answer_contract_names_no_real_corpus_document():
    """An id in the system prompt is handed to the model on every question.

    Two real ids used to sit in the example, and between them they were the
    gold citation for thirteen questions, which inflated the evidence
    diagnostics of every submission.
    """
    from bench.answer_contract import ANSWER_CONTRACT

    cited = {sid for g in GOLD for sid in (g.get("gold_source_ids") or [])}
    leaked = sorted(sid for sid in cited if sid in ANSWER_CONTRACT)
    assert not leaked, f"the answer contract names real corpus documents: {leaked}"
