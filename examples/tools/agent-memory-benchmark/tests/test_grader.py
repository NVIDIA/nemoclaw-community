# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Grading rules are the benchmark's contract — they get tested like code."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.grader import grade, score_evidence  # noqa: E402
from bench.normalize import contains, normalize  # noqa: E402


def test_dates_normalize_across_spellings():
    forms = ["May 28, 2026", "2026-05-28", "28 May 2026", "may 28"]
    assert len({normalize(f) for f in forms}) == 1


def test_slash_dates_are_us_month_first():
    assert normalize("6/8") == normalize("June 8")


def test_single_token_match_respects_boundaries():
    assert contains("the threshold is 16k tokens", "16k")
    assert not contains("the threshold is 116k tokens", "16k")


def test_string_any_accepts_a_variant():
    verdict = grade("q", "Launch is July 14.", None, {"mode": "string_any", "accept": ["2026-07-14"]})
    assert verdict.correct


def test_string_any_rejects_a_stale_assertion_even_with_the_right_words_nearby():
    gold = {"mode": "string_any", "accept": ["2026-07-14"], "reject": ["launch is june 30"]}
    assert not grade("q", "The launch is June 30, not July 14.", None, gold).correct


def test_require_all_needs_every_element():
    gold = {"mode": "string_any", "require_all": ["50%", "75%"]}
    assert grade("q", "50% reached, 75% is next.", None, gold).correct
    assert not grade("q", "It reached 50%.", None, gold).correct


def test_boolean_polarity():
    gold = {"mode": "boolean", "expected": "no"}
    assert grade("q", "No, they are two distinct reviews.", None, gold).correct
    assert not grade("q", "Yes, same review.", None, gold).correct


def test_boolean_without_clear_polarity_is_not_credited():
    assert not grade("q", "It depends how you look at it.", None, {"mode": "boolean", "expected": "yes"}).correct


def test_abstention_requires_declining():
    gold = {"mode": "abstain", "reject": ["project phoenix is"]}
    assert grade("q", "The corpus has no mention of that project.", None, gold).correct
    assert not grade("q", "Project Phoenix is a metrics pipeline.", None, gold).correct


def test_empty_answer_counts_as_abstention_not_as_a_claim():
    assert grade("q", "", None, {"mode": "abstain"}).correct


def test_evidence_is_none_when_the_system_cited_nothing():
    assert score_evidence(None, ["E:a"]) == (None, None)
    assert score_evidence([], ["E:a"]) == (None, None)


def test_evidence_recall_and_precision():
    recall, precision = score_evidence(["E:a", "E:x"], ["E:a", "E:b"])
    assert recall == 0.5
    assert precision == 0.5


def test_llm_mode_defers_rather_than_guessing():
    verdict = grade("q", "anything", None, {"mode": "llm"})
    assert verdict.correct is None and verdict.needs_llm


def test_runner_resolves_paths_to_absolute():
    """A relative path reaches adapters that re-spawn with a different cwd."""
    source = (Path(__file__).resolve().parents[1] / "bench" / "runner.py").read_text(encoding="utf-8")
    assert "args.state = args.state.resolve()" in source
    assert '(args.state or run_dir / "state").resolve()' in source


def test_weekday_abbreviations_match_full_names():
    assert contains("Monday EOD", "Mon EOD")


def test_spelled_out_durations_match_short_forms():
    assert contains("about 24 seconds of degraded performance", "24s")
    assert contains("lowered to 14 days", "14d")


def test_unit_canonicalization_does_not_merge_distinct_numbers():
    assert not contains("25 seconds", "24s")
