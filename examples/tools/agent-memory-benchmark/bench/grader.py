# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic grading for mnemo-benchmark answers.

Every shipped question is graded without a model: the gold entry names the
strings that must appear (``accept``), the stale or fabricated strings that must
not (``reject``), and — for questions where the honest answer is "the corpus
does not say" — the abstention contract. A free-text explanation question would
need ``mode: llm`` and a judge model to resolve it. No shipped question uses
that mode, and keeping it empty is a design goal rather than an accident,
because a judge model is a moving part this benchmark cannot pin forever.

Every mode returns the same :class:`Verdict` so the report never has to care how
a question was scored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from bench.normalize import contains, normalize

# Phrases a system uses when it declines to answer. Deliberately broad: a system
# that hedges ("I could not find anything about X") is abstaining, and the
# benchmark should credit that rather than punish phrasing.
ABSTAIN_MARKERS = (
    "i don't know", "i do not know", "unknown", "not known", "no information",
    "not mentioned", "nothing in the corpus", "not in the corpus", "no record",
    "not found", "could not find", "couldn't find", "no evidence", "not stated",
    "does not appear", "doesn't appear", "no mention", "not present",
    "cannot determine", "can't determine", "unable to determine", "insufficient",
    "no such", "does not exist", "doesn't exist", "never created", "not created",
    "not documented", "no data", "no corpus evidence", "no evidence in the corpus",
    "not resolved", "was not resolved", "still pending", "only reserved",
    "only planned", "not opened", "no outcome", "has not happened", "not yet happened",
    "did not happen", "no record of", "nothing in the raw", "does not state",
    "doesn't state", "does not say", "doesn't say", "corpus only shows",
    "only reserved", "no opened", "never opened", "not reviewed",
)

YES_MARKERS = ("yes", "correct", "true", "that is right", "same person", "one person", "identical")
NO_MARKERS = ("no", "not the same", "incorrect", "false", "different", "two distinct", "separate")


@dataclass
class Verdict:
    """Outcome of grading one answer."""

    question_id: str
    correct: bool | None  # None => mode llm, which no shipped question uses
    mode: str
    reason: str = ""
    evidence_recall: float | None = None
    evidence_precision: float | None = None
    cited: list[str] = field(default_factory=list)
    needs_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "correct": self.correct,
            "mode": self.mode,
            "reason": self.reason,
            "evidence_recall": self.evidence_recall,
            "evidence_precision": self.evidence_precision,
            "cited": self.cited,
            "needs_llm": self.needs_llm,
        }


def _hit(answer: str, needles: Iterable[str]) -> str | None:
    for needle in needles:
        if contains(answer, needle):
            return needle
    return None


def _is_abstention(answer: str) -> bool:
    text = normalize(answer)
    if not text:
        return True  # an empty answer is a (poorly phrased) refusal, not a claim
    return any(normalize(marker) in text for marker in ABSTAIN_MARKERS)


def _grade_string_any(answer: str, gold: dict) -> tuple[bool, str]:
    rejected = _hit(answer, gold.get("reject", []))
    if rejected:
        return False, f"asserted rejected value: {rejected!r}"
    accept = gold.get("accept", [])
    require_all = gold.get("require_all", [])
    missing = [item for item in require_all if not contains(answer, item)]
    if missing:
        return False, f"missing required element(s): {missing}"
    if not accept:
        return bool(require_all), "all required elements present"
    matched = _hit(answer, accept)
    if matched:
        return True, f"matched {matched!r}"
    return False, "no accepted value found in the answer"


def _grade_boolean(answer: str, gold: dict) -> tuple[bool, str]:
    expected = str(gold["expected"]).lower()  # "yes" / "no"
    text = normalize(answer)
    lead = text[:220]
    said_yes = any(re.search(rf"(?<![a-z]){re.escape(normalize(m))}(?![a-z])", lead) for m in YES_MARKERS)
    said_no = any(re.search(rf"(?<![a-z]){re.escape(normalize(m))}(?![a-z])", lead) for m in NO_MARKERS)
    rejected = _hit(answer, gold.get("reject", []))
    if rejected:
        return False, f"asserted rejected value: {rejected!r}"
    if said_yes == said_no:
        # Ambiguous or absent polarity: fall back to the required elements.
        missing = [item for item in gold.get("require_all", []) if not contains(answer, item)]
        if gold.get("require_all") and not missing:
            return expected == "yes", "polarity implicit; required elements present"
        return False, "answer states neither yes nor no clearly"
    given = "yes" if said_yes else "no"
    if given != expected:
        return False, f"answered {given}, expected {expected}"
    missing = [item for item in gold.get("require_all", []) if not contains(answer, item)]
    if missing:
        return False, f"correct polarity but missing: {missing}"
    return True, f"answered {given}"


def _grade_abstain(answer: str, gold: dict) -> tuple[bool, str]:
    # Order matters: "Project Phoenix is not in the corpus" contains the same
    # substring as a fabricated claim about Project Phoenix. Declining first
    # keeps a correct refusal from being read as the thing it refuses.
    if _is_abstention(answer):
        return True, "correctly declined to assert"
    # Some questions are answerable by rejecting their premise instead of
    # declining ("ReviewBot is an automated sender, not a colleague"). These
    # markers are NOT a correct answer to the question as asked — an abstention
    # item has none — so they live under their own key.
    premise = _hit(answer, gold.get("accept_as_decline", []))
    if premise:
        return True, f"rejected the question's premise ({premise!r})"
    fabricated = _hit(answer, gold.get("reject", []))
    if fabricated:
        return False, f"asserted content the corpus does not support: {fabricated!r}"
    return False, "answered as if the fact were known (no abstention marker)"


def _grade_ordering(answer: str, gold: dict) -> tuple[bool, str]:
    """Every element present, in the order the corpus puts them.

    Ordering questions are the cheapest way to ask for something a single page
    cannot answer: the system has to place events relative to each other, which
    means holding several dates at once rather than looking one up.
    """
    text = normalize(answer)
    positions: list[tuple[int, str]] = []
    for element in gold["sequence"]:
        aliases = element if isinstance(element, list) else [element]
        found = [text.find(normalize(a)) for a in aliases if normalize(a) in text]
        if not found:
            return False, f"missing element: {aliases[0]!r}"
        positions.append((min(found), aliases[0]))
    order = [pos for pos, _ in positions]
    if order != sorted(order):
        stated = [label for _, label in sorted(positions)]
        return False, f"elements present but ordered {stated}"
    return True, "correct order"


_MODES = {
    "string_any": _grade_string_any,
    "boolean": _grade_boolean,
    "abstain": _grade_abstain,
    "ordering": _grade_ordering,
}


def score_evidence(cited: list[str] | None, gold_ids: list[str] | None) -> tuple[float | None, float | None]:
    """Recall/precision of cited source ids against the gold set.

    Returns ``(None, None)`` when the question has no gold ids or the system
    cited nothing — "did not participate" must not be scored as zero, or a
    system without provenance support would be penalized twice (once here and
    once in the leaderboard's n/a column).
    """
    if not gold_ids:
        return None, None
    if not cited:
        return None, None
    gold_set = {g.strip() for g in gold_ids}
    cited_set = {c.strip() for c in cited}
    hit = len(gold_set & cited_set)
    return hit / len(gold_set), hit / len(cited_set)


def grade(question_id: str, answer: str, cited: list[str] | None, gold: dict) -> Verdict:
    """Grade one answer against its gold entry."""
    mode = gold.get("mode", "string_any")
    recall, precision = score_evidence(cited, gold.get("gold_source_ids"))
    if mode == "llm":
        return Verdict(
            question_id=question_id,
            correct=None,
            mode=mode,
            reason="deferred to judge model",
            evidence_recall=recall,
            evidence_precision=precision,
            cited=list(cited or []),
            needs_llm=True,
        )
    handler = _MODES.get(mode)
    if handler is None:
        raise ValueError(f"{question_id}: unknown grading mode {mode!r}")
    correct, reason = handler(answer or "", gold)
    return Verdict(
        question_id=question_id,
        correct=correct,
        mode=mode,
        reason=reason,
        evidence_recall=recall,
        evidence_precision=precision,
        cited=list(cited or []),
    )
