# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The shipped corpus, questions, and answer key must agree with each other."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_every_manifest_document_exists():
    for row in _jsonl(REPO / "corpus" / "manifest.jsonl"):
        assert (REPO / "corpus" / row["path"]).exists(), row["doc_id"]


def test_every_gold_citation_resolves_to_a_document():
    known = {row["doc_id"] for row in _jsonl(REPO / "corpus" / "manifest.jsonl")}
    for gold in _jsonl(REPO / "gold" / "answers.jsonl"):
        for source_id in gold.get("gold_source_ids", []):
            assert source_id in known, f"{gold['id']} cites missing document {source_id}"


def test_questions_and_gold_are_one_to_one():
    questions = {q["id"] for q in _jsonl(REPO / "questions" / "questions.jsonl")}
    golds = {g["id"] for g in _jsonl(REPO / "gold" / "answers.jsonl")}
    assert questions == golds


def test_abstention_questions_have_no_accepted_answer():
    """An abstention item has no correct answer — only markers for declining.

    ``accept_as_decline`` is allowed and means "this phrasing rejects the
    question's premise", which is a way of declining, not an answer.
    """
    for gold in _jsonl(REPO / "gold" / "answers.jsonl"):
        if gold["type"] == "abstention":
            assert gold["mode"] == "abstain"
            assert not gold.get("accept"), f"{gold['id']} cannot have a correct answer"
            assert gold.get("reject"), f"{gold['id']} must name the fabrication it guards against"


def test_corpus_is_split_across_both_halves():
    parts = {row["part"] for row in _jsonl(REPO / "corpus" / "manifest.jsonl")}
    assert parts == {"part_a", "part_b"}
