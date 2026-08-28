# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Corpus B held to the same answer-key invariants as corpus A.

Corpus B shipped covered only by its content hash, so a defect in its grading
rules could not fail a test. Running corpus A's invariants against it by hand
found three: a question whose cited document has no body, a truncated name in
an `accept` list that matched the real one by substring, and six abstention
items with no `reject`. Those are fixed; this file keeps them fixed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bench.grader import normalize  # noqa: E402

QUESTIONS = [json.loads(line) for line in
             (REPO / "corpus_b" / "questions" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
GOLD = [json.loads(line) for line in
        (REPO / "corpus_b" / "questions" / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
MANIFEST = [json.loads(line) for line in
            (REPO / "corpus_b" / "corpus" / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
DOC_IDS = {row["doc_id"] for row in MANIFEST}
COMMON = {"still", "open", "yes", "no", "done", "not", "none", "some", "was", "is", "the"}


def _body(doc_id: str) -> str:
    path = next(REPO / "corpus_b" / "corpus" / m["path"] for m in MANIFEST if m["doc_id"] == doc_id)
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[-1].strip() if text.startswith("---") else text.strip()


def test_questions_and_answer_key_agree_on_which_questions_exist():
    assert {q["id"] for q in QUESTIONS} == {g["id"] for g in GOLD}


def test_question_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_gold_citation_points_at_a_document_that_exists():
    dangling = [(g["id"], s) for g in GOLD for s in (g.get("gold_source_ids") or []) if s not in DOC_IDS]
    assert not dangling, dangling


def test_no_question_cites_a_document_with_no_body():
    """A question whose evidence is empty cannot be answered from the corpus."""
    empty = [(g["id"], s) for g in GOLD for s in (g.get("gold_source_ids") or []) if not _body(s)]
    assert not empty, f"gold citations with no body: {empty}"


def test_no_accepted_answer_is_a_bare_common_word():
    offenders = [(g["id"], a) for g in GOLD for a in g.get("accept", [])
                 if str(a).strip().lower() in COMMON]
    assert not offenders, offenders


def test_no_string_is_both_accepted_and_rejected():
    clashes = [(g["id"], sorted({normalize(str(a)) for a in g.get("accept", [])}
                                & {normalize(str(r)) for r in g.get("reject", [])}))
               for g in GOLD
               if {normalize(str(a)) for a in g.get("accept", [])}
               & {normalize(str(r)) for r in g.get("reject", [])}]
    assert not clashes, clashes


def test_every_abstention_item_names_the_fabrication_it_guards_against():
    bare = [g["id"] for g in GOLD if g.get("mode") == "abstain" and not g.get("reject")]
    assert not bare, f"abstention items with no reject: {bare}"


def test_abstention_items_have_no_accepted_answer():
    offenders = [g["id"] for g in GOLD if g.get("mode") == "abstain" and g.get("accept")]
    assert not offenders, offenders


def test_every_grading_mode_is_one_the_grader_implements():
    unknown = {g.get("mode", "string_any") for g in GOLD} - {"string_any", "boolean", "abstain", "ordering"}
    assert not unknown, unknown


def test_every_drafted_question_is_published_or_recorded_as_dropped():
    base = REPO / "corpus_b" / "questions"
    published = {q["id"] for q in QUESTIONS}
    dropped = {d.get("id") for d in json.loads((base / "factual_dropped.json").read_text())}
    dropped |= {d.get("id") for d in json.loads((base / "dropped.json").read_text())}
    drafted = {i.get("id") for i in json.loads((base / "factual_items.json").read_text())}
    orphans = sorted(drafted - published - dropped)
    assert not orphans, f"drafted, then neither published nor recorded as dropped: {orphans}"


def test_the_documented_counts_match_the_shipped_question_set():
    """A drop that is not reflected in the prose leaves two truths in the tree.

    Dropping one question moved the total from 97 to 96, and the submission
    guide and the catalog each stated it separately.
    """
    import re

    guide = (REPO / "docs" / "SUBMITTING.md").read_text(encoding="utf-8")
    stated = re.search(r"Corpus B is (\d+) questions over (\d+) documents", guide)
    assert stated, "the submission guide no longer states corpus B's size"
    assert int(stated.group(1)) == len(QUESTIONS)
    assert int(stated.group(2)) == len(MANIFEST)

    # Find this example's catalog row and read the numbers out of it, rather than
    # matching the sentence around them. A maintainer reworded that sentence
    # upstream -- "asks ... on a second" became "asking ... on another" -- and a
    # regex pinned to the prose went red on main without a number having moved.
    catalog = (REPO.parents[1] / "README.md").read_text(encoding="utf-8")
    row = next((line for line in catalog.splitlines()
                if "agent-memory-benchmark" in line and line.startswith("|")), None)
    assert row, "the example catalog no longer lists this example"
    counts = [int(n) for n in re.findall(r"\b(\d{2,4}) questions?\b|\band (\d{2,4})\b", row)
              for n in ([n[0] or n[1]]) if n]
    assert len(QUESTIONS) in counts, (
        f"the catalog row states {counts}; corpus B ships {len(QUESTIONS)} questions. "
        f"Row: {row.strip()[:160]}")
