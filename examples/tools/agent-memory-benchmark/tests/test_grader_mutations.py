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

import pytest
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


# Each of these was reported as a bypass or a false rejection against the first
# version of the denial scope. They are kept as a table so the contract is
# readable in one place and a future refinement has to satisfy all of it.
DENIAL_SCOPE_CONTRACT = [
    ("a denial that introduces a list governs the list",
     {"mode": "string_any", "accept": ["50%", "75%"]},
     "None of these are correct: 50%; 75%", False),
    ("a refusal does not license the fabrication after it",
     {"mode": "abstain", "reject": ["the cutover completed"]},
     "No evidence in the corpus. The cutover completed", False),
    ("a denial applies to a value that matched only after normalisation",
     {"mode": "string_any", "accept": ["2026-07-14"]},
     "None of these dates is correct: July 14, 2026", False),
    ("a denial after the value still denies it",
     {"mode": "string_any", "accept": ["50%"]}, "50% is not correct", False),
    ("neither/nor governs both items",
     {"mode": "string_any", "accept": ["50%", "75%"]},
     "Neither 50%, nor 75% is correct", False),
    ("a comma before a denial does not reset it",
     {"mode": "string_any", "accept": ["2026-07-14"], "reject": ["launch is june 30"]},
     "The launch is June 30, not July 14.", False),
    ("rather-than names the rejected thing, not the asserted one",
     {"mode": "string_any", "accept": ["Sofia Ramos"], "reject": ["Kofi"]},
     "Sofia Ramos rather than Kofi approved it", True),
    ("instead-of behaves the same way",
     {"mode": "string_any", "accept": ["Sofia"], "reject": ["Kofi"]},
     "Sofia instead of Kofi", True),
    ("a semicolon ends a denial so the correction scores",
     {"mode": "string_any", "accept": ["Sofia"], "reject": ["Kofi"]},
     "It was not Kofi; Sofia approved it", True),
    ("a comma ends a denial so the correction scores",
     {"mode": "string_any", "accept": ["27 March"]},
     "Not 12 March, it is on 27 March.", True),
    ("a denial in one sentence does not reach the next",
     {"mode": "string_any", "accept": ["75%"]},
     "50% is not correct. The target is 75%.", True),
    ("a dot inside a path does not end the sentence",
     {"mode": "string_any", "accept": ["src/a/b.py"]}, "It is not src/a/b.py", False),
    ("a plain assertion is still an assertion",
     {"mode": "string_any", "accept": ["50%"]}, "It is at 50%.", True),
    ("not-X-but-Y is a correction, not a denial of Y",
     {"mode": "string_any", "accept": ["Sofia"], "reject": ["Kofi"]},
     "Not Kofi but Sofia approved it", True),
    ("a denial parenthesised by commas does not deny the subject",
     {"mode": "string_any", "accept": ["Sofia"], "reject": ["Kofi"]},
     "Sofia, not Kofi, approved it", True),
    ("a denial after a semicolon does not reach back over it",
     {"mode": "string_any", "accept": ["75%"]},
     "75% is correct; 50% is incorrect", True),
    ("a contrast nested inside a denial cannot lift itself out",
     {"mode": "string_any", "accept": ["Sofia"]},
     "None of these are correct: Sofia rather than Kofi", False),
    ("a thousands separator is not a clause boundary",
     {"mode": "string_any", "accept": ["55,000"], "require_all": ["55,000", "40,000"]},
     "It is now 55,000, revised up from 40,000.", True),
    # A colon can introduce a denied set or a correction. Both directions,
    # because narrowing the colon rule to set denials could have re-opened the
    # attack it was added to block.
    ("a value-scoped denial before a colon does not deny the correction after it",
     {"mode": "string_any", "accept": ["75%"]},
     "The answer is not 50%: it is 75%", True),
    ("that same colon leaves the denied value denied",
     {"mode": "string_any", "accept": ["50%"]},
     "The answer is not 50%: it is 75%", False),
    ("a rejecting contrast before a colon still asserts the kept value",
     {"mode": "string_any", "accept": ["Sofia"]},
     "Sofia rather than Kofi: she approved it", True),
    ("that same contrast leaves the rejected value denied",
     {"mode": "string_any", "accept": ["Kofi"]},
     "Sofia rather than Kofi: she approved it", False),
    ("a set denial before a colon still governs the list it introduces",
     {"mode": "string_any", "accept": ["Sofia"]},
     "None of these are correct: Sofia rather than Kofi", False),
    # Denial that follows the value, and denial by exclusion: neither negates a
    # verb ahead of the value, so both slipped past the cue list.
    ("a denial that follows the value denies it",
     {"mode": "string_any", "accept": ["50%"]}, "50% is wrong", False),
    ("a correction phrased the same way still asserts its own value",
     {"mode": "string_any", "accept": ["75%"]}, "50% is wrong; it is 75%", True),
    ("exclusion denies the value it carves out",
     {"mode": "string_any", "accept": ["50%"]}, "Anything except 50%", False),
    ("exclusion does not deny the value it keeps",
     {"mode": "string_any", "accept": ["75%"]}, "75%, anything except 50%", True),
    # Found in a published answer, not invented: a closing quote after the
    # period keeps the sentence from ending, so the run-on reaches a later
    # colon and the old rule let an "instead of" ahead of that colon deny the
    # quoted assertion. The score survived only because a second accepted value
    # matched, which is exactly how a defect like this stays invisible.
    ("a quote that defers the sentence break does not extend a denial over a colon",
     {"mode": "string_any", "accept": ["protected"]},
     'Jordan confirmed "protected mornings already helped this week, got the '
     'migration script reviewable in one sitting instead of three." The third '
     'burden was addressed by setting a boundary: "just do not let it become a '
     'recurring meeting."', True),
    # Cues were matched as raw substrings, so a cue could fire across a token
    # boundary and deny a clause that says the opposite. Both directions: the
    # cue must still deny when it is a real cue.
    ("a cue that only appears across a token boundary does not deny",
     {"mode": "string_any", "accept": ["75%"]},
     "This wrong estimate was corrected to 75%", True),
    ("the same, with a different verb",
     {"mode": "string_any", "accept": ["75%"]},
     "This wrong value was replaced with 75%", True),
    # Taken from the published self-model run, where "is not" matched inside
    # "is noted" and cost the answer its point.
    ("'is noted' is not 'is not'",
     {"mode": "string_any", "accept": ["Jin Oh"]},
     "Jin Oh (Jin) is noted as representing the ML-research side in the "
     "Beacon eval methodology walkthrough.", True),
    ("the cue still denies when it is really there",
     {"mode": "string_any", "accept": ["50%"]}, "The figure is not 50%", False),
]


@pytest.mark.parametrize(
    "label,gold,answer,expected", DENIAL_SCOPE_CONTRACT,
    ids=[c[0].replace(" ", "-") for c in DENIAL_SCOPE_CONTRACT])
def test_the_denial_scope_contract(label, gold, answer, expected):
    """Both directions matter: a bypass scores an attack, a false rejection
    marks a correct answer wrong. The first version of this scope did both."""
    gold = {"id": "q", **gold}
    assert grade("q", answer, None, gold).correct is expected, label
