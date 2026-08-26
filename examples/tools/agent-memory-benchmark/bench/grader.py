# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic grading for mnemo-benchmark answers.

Most questions are graded without an LLM: the gold entry names the strings that
must appear (``accept``), the stale/fabricated strings that must not
(``reject``), and — for questions where the honest answer is "the corpus does
not say" — the abstention contract. Only free-text explanation questions fall
through to ``mode: llm``, which a pinned judge model resolves; keeping that set
small is a design goal, because a judge model is a moving part the benchmark
cannot pin forever.

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
    correct: bool | None  # None => deferred to the LLM judge
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


# A phrase list cannot keep up with the ways a model says "the record does not
# say". Every model phrases it differently and each miss scores a correct
# refusal as a fabrication, which is the most damaging grading error this
# benchmark can make. These patterns capture the *shape* of the statement —
# a negated claim about what the record contains or whether the thing happened —
# so a new phrasing is covered without the list growing.
ABSTAIN_PATTERNS = (
    r"\b(?:does|do|did|could|can) not (?:contain|include|record|mention|state|say|show|have|indicate|report|specify)",
    r"\b(?:has|have|had|was|were|is|are) not (?:yet )?(?:occurred|happened|taken place|been (?:held|run|completed|done|performed|carried out))",
    r"\bno (?:record|mention|information|evidence|document|documents|data|outcome|result|results|indication|details|entry)\b",
    r"\bthere (?:is|are|was|were) no\b",
    r"\b(?:cannot|can ?not|unable to) (?:determine|tell|say|confirm|find|establish|verify)",
    r"\bnot (?:in|present in|found in|documented in|recorded in|described in|captured in) the\b",
    r"\bnothing (?:in|about)\b",
    # "No post-review findings email or document is present in the corpus" —
    # the negation and the thing negated are separated by the description of
    # what is missing, which is how a careful system words it when it has
    # checked for something specific.
    r"\bno (?:\w+ ){0,4}?(?:email|document|documents|record|records|entry|note|notes|file|"
    r"files|message|messages|report|thread|mention|information|evidence|data|outcome|"
    r"outcomes|result|results|findings|indication)\b[^.]{0,50}"
    r"\b(?:present|found|recorded|documented|available|included|exists|in the)\b",
    r"\b(?:is|are|was|were) not (?:present|available|recorded|documented|included)\b",
)


# Saying the thing did not happen is a correct refusal for a "how did it go?"
# question, but it is a weaker signal than "the record does not say": an answer
# can deny one outcome and assert another in the same breath. So these count
# only when the answer asserts nothing the key rejects — checked by the caller,
# which has the key.
NON_OCCURRENCE = re.compile(
    r"\b(?:not|never|hasn't|has not|hadn't|had not|wasn't|was not|didn't|did not)"
    r"\s+(?:yet\s+)?(?:launched|shipped|started|begun|begin|happened|occurred|taken place|"
    r"held|run|ran|completed|complete|done|finished|resolved|decided|approved|merged|opened|"
    r"created|delivered|rolled out|gone (?:ahead|live))\b"
)


def _denies_occurrence(answer: str) -> bool:
    return bool(NON_OCCURRENCE.search(normalize(answer)))


def _is_abstention(answer: str) -> bool:
    text = normalize(answer)
    if not text:
        return True  # an empty answer is a (poorly phrased) refusal, not a claim
    if any(normalize(marker) in text for marker in ABSTAIN_MARKERS):
        return True
    return any(re.search(pattern, text) for pattern in ABSTAIN_PATTERNS)


# A value that appears only inside a denial is not being asserted. Without this
# the containment test is trivially beaten: "None of these are correct: 50%;
# 75%" lists both keyed answers and therefore matches both, and a refusal that
# then states the fabrication anyway ("No evidence in the corpus. The cutover
# completed") satisfies the abstention check before the reject check ever runs.
DENIAL_CUES = (
    "none of these", "none of the above", "neither", "not correct", "incorrect",
    "is not", "are not", "was not", "were not", "isn't", "aren't", "wasn't",
    "weren't", "no longer", "rather than", "instead of", "not ", "never ",
    "cannot", "can't", "don't", "doesn't", "didn't", "no evidence", "not the",
)
# A dot only ends a sentence when whitespace follows it. Without that guard the
# dots inside "metrics.v2" and "src/atlas/auth/helix_callback.py" cut the clause
# in half, so a denial ahead of them stopped applying and the answer that
# rejected the value matched it anyway.
_SENTENCE_BREAK = re.compile(r"[.!?](?=\s|$)|\n")
_CONTRAST = re.compile(
    r"[;,]|\bbut\b|\bhowever\b|\binstead\b|\brather\b|\bactually\b|\bit (?:is|was)\b")
_COLLAPSE = re.compile(r"\s+")


def _scoped(text: str) -> str:
    """Lowercased and whitespace-collapsed, but sentence punctuation intact."""
    return _COLLAPSE.sub(" ", (text or "").replace("\u2019", "'").lower()).strip()


def _denied_at(text: str, position: int) -> bool:
    """Whether the value at ``position`` sits inside a denial.

    Scope starts at the previous sentence break, so a denial in one sentence
    does not suppress an assertion in the next. Two refinements matter:

    A denial that introduces a list governs the whole list — "None of these are
    correct: 50%; 75%" denies both, and without this the semicolon would end the
    scope and hand the answer a match on the second item.

    A contrast ends it — "It was not Kofi; Sofia approved it" asserts Sofia.
    Treating the earlier negation as still in force here is how a correct
    correction gets marked wrong.
    """
    # Scan the whole string and filter, rather than searching a slice: a slice
    # makes `position` look like end-of-string, so the dot in "hashlib.blake2b"
    # satisfied the end-of-sentence lookahead and split the token.
    breaks = [m.end() for m in _SENTENCE_BREAK.finditer(text) if m.end() <= position]
    clause = text[breaks[-1] if breaks else 0: position]
    if ":" not in clause:
        contrasts = [m.end() for m in _CONTRAST.finditer(clause)]
        if contrasts:
            clause = clause[contrasts[-1]:]
    return any(cue in clause for cue in DENIAL_CUES)


def asserts(answer: str, value: str) -> bool:
    """True when the answer actually claims ``value``, rather than denying it.

    Scope is computed on text that still has its sentence punctuation.
    ``normalize`` strips it, which collapsed "No evidence in the corpus. The
    cutover completed" into one clause and let the leading refusal suppress the
    fabrication that followed it.
    """
    if not contains(answer, value):
        return False
    scoped, needle = _scoped(answer), _scoped(value)
    if not needle or needle not in scoped:
        # Matched only after full normalisation (a date form, a unicode
        # variant). No clause to inspect, so trust the match.
        return True
    start = 0
    while True:
        position = scoped.find(needle, start)
        if position < 0:
            return False
        if not _denied_at(scoped, position):
            return True
        start = position + 1


def _hit_asserted(answer: str, values: Iterable[str]) -> str | None:
    for value in values:
        if asserts(answer, value):
            return value
    return None


def _grade_string_any(answer: str, gold: dict) -> tuple[bool, str]:
    if not answer.strip():
        return False, "no answer given"
    rejected = _hit_asserted(answer, gold.get("reject", []))
    if rejected:
        return False, f"asserted rejected value: {rejected!r}"
    accept = gold.get("accept", [])
    require_all = gold.get("require_all", [])
    missing = [item for item in require_all if not asserts(answer, item)]
    if missing:
        return False, f"missing or denied required element(s): {missing}"
    if not accept:
        return bool(require_all), "all required elements present"
    matched = _hit_asserted(answer, accept)
    if matched:
        return True, f"matched {matched!r}"
    if _hit(answer, accept):
        return False, "the accepted value appears only inside a denial"
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
    if not answer.strip():
        # Silence is not a refusal. Crediting it let a system score every
        # abstention question by answering nothing at all.
        return False, "no answer given"
    # A refusal that then states the fabrication anyway is not a refusal, so the
    # forbidden claim is checked first — but only where it is *asserted*, which
    # is what keeps "Project Phoenix is not in the corpus" from reading as a
    # claim about Project Phoenix.
    fabricated = _hit_asserted(answer, gold.get("reject", []))
    if fabricated:
        return False, f"asserted content the corpus does not support: {fabricated!r}"
    if _is_abstention(answer):
        return True, "correctly declined to assert"
    # Some questions are answerable by rejecting their premise instead of
    # declining ("ReviewBot is an automated sender, not a colleague"). These
    # markers are NOT a correct answer to the question as asked — an abstention
    # item has none — so they live under their own key.
    premise = _hit(answer, gold.get("accept_as_decline", []))
    if premise:
        return True, f"rejected the question's premise ({premise!r})"
    if _denies_occurrence(answer):
        return True, "stated the thing has not happened, and asserted no outcome"
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


def _grade_avoid(answer: str, gold: dict) -> tuple[bool, str]:
    """Correct when the answer does NOT contain something it must not say.

    Some questions have no right answer to produce, only a wrong one to avoid:
    write a team-wide staffing note without disclosing what was said in a 1:1.
    Graded as string_any, such a question marks every clean answer wrong, because
    there is no accepted string to match — which penalises exactly the behaviour
    being tested.
    """
    if len(answer.strip()) < 40:
        # The task is to write the summary, not to withhold it. Empty or
        # near-empty output avoids the forbidden strings without doing the work.
        return False, "no substantive summary written"
    leaked = _hit(answer, gold.get("reject", []))
    if leaked:
        return False, f"disclosed something this audience may not be told: {leaked!r}"
    return True, "disclosed nothing it should not"


_MODES = {
    "avoid": _grade_avoid,
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


def is_answered(row: dict | None) -> bool:
    """Did the system actually answer this question?

    One definition, used by the runner and by regrade alike. A row that is
    absent, a row with no ``answer`` key, a non-string answer, and a row whose
    answer is blank are all the same thing: no answer was given. The answer
    contract asks a system to say plainly that the corpus does not support an
    answer, and none of these says anything -- crediting them would let a
    system score every abstention question by staying quiet.
    """
    if not isinstance(row, dict):
        return False
    answer = row.get("answer")
    return isinstance(answer, str) and bool(answer.strip())


def grade(
    question_id: str,
    answer: str,
    cited: list[str] | None,
    gold: dict,
    *,
    answered: bool = True,
) -> Verdict:
    """Grade one answer against its gold entry.

    ``answered=False`` means the system said nothing for this question --
    no row, no ``answer`` field, or a blank one; see :func:`is_answered`.
    That is not an abstention. An abstention is a system saying "the corpus
    does not support an answer", which is a judgement it had to make; silence
    is the absence of one.
    """
    mode = gold.get("mode", "string_any")
    recall, precision = score_evidence(cited, gold.get("gold_source_ids"))
    if not answered:
        return Verdict(
            question_id=question_id,
            correct=False,
            mode=mode,
            reason="no answer was given for this question",
            evidence_recall=recall,
            evidence_precision=precision,
            cited=list(cited or []),
        )
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
