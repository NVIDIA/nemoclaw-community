# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Attack every shipped answer key, so a grading hole cannot ship quietly.

A grading contract is only as good as the worst answer that satisfies it. These
tests generate hostile answers from the keys themselves — deny the right value,
say nothing, refuse and then fabricate anyway — and require that none of them
score. They are generated rather than written out, so a key added later is
attacked without anyone remembering to attack it.

All three attacks used to pass on essentially every key: 333/333 string_any
items credited an answer that explicitly denied each accepted value, 40/40
abstention items credited an empty string, and 26/26 credited a refusal that
then stated the forbidden claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from bench.grader import grade

REPO = Path(__file__).resolve().parents[1]
KEYS = ("gold/answers.jsonl", "corpus_b/questions/answers.jsonl",
        "corpus_c/questions/answers.jsonl", "corpus_d/questions/answers.jsonl")


def _gold() -> list[dict]:
    rows = []
    for name in KEYS:
        path = REPO / name
        if path.exists():
            rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows


def _accepted(gold: dict) -> list[str]:
    return [str(v) for v in (gold.get("accept") or []) + (gold.get("require_all") or [])]


def test_denying_every_accepted_value_never_scores():
    """Listing the right answer in order to reject it must not match it.

    Exempt keys whose accepted value is short enough to occur inside the attack
    sentence itself ("no", "419"); those are flagged separately as keys that
    need tightening, and are not evidence about the grader.
    """
    survivors = []
    for gold in _gold():
        values = _accepted(gold)
        if gold.get("mode") != "string_any" or not values:
            continue
        if any(len(v.strip()) <= 4 or v.strip().isdigit() for v in values):
            continue
        answer = "None of these are correct: " + "; ".join(values)
        if grade(gold["id"], answer, None, gold).correct:
            survivors.append(gold["id"])
    assert not survivors, f"denial scored on {len(survivors)} keys: {survivors[:5]}"


def test_saying_nothing_never_scores():
    survivors = [g["id"] for g in _gold()
                 if g.get("mode") in ("string_any", "abstain", "avoid")
                 and grade(g["id"], "", None, g).correct]
    assert not survivors, f"empty answer scored on {len(survivors)} keys: {survivors[:5]}"


def test_refusing_and_then_fabricating_never_scores():
    survivors = []
    for gold in _gold():
        if gold.get("mode") != "abstain" or not gold.get("reject"):
            continue
        answer = f"No evidence in the corpus. {gold['reject'][0]}"
        if grade(gold["id"], answer, None, gold).correct:
            survivors.append(gold["id"])
    assert not survivors, f"refuse-then-fabricate scored on {len(survivors)} keys: {survivors[:5]}"


def test_a_correction_after_a_denial_still_scores():
    """The fix must not swing the other way and fail honest corrections."""
    gold = {"id": "q", "mode": "string_any", "accept": ["Sofia Ramos"]}
    assert grade("q", "It was not Kofi; Sofia Ramos approved it.", None, gold).correct
    gold = {"id": "q", "mode": "string_any", "accept": ["27 March"]}
    assert grade("q", "Not 12 March, it is on 27 March.", None, gold).correct
