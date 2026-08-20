# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Edge cases for the cap-and-cascade arithmetic. No model, no tokens."""

import sys, unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ranking import HIGH_CAP, MEDIUM_CAP, rank_population  # noqa: E402


def rows(spec):
    """spec is a string of g/u — g = passes the intent gate, u = does not.

    `batch_rank` carries the order the model returned, which is what the
    population sort falls back to within a gate class.
    """
    return [{"source_id": f"i{n}", "intent_gated": (c == "g"),
             "manual_priority": None, "batch_rank": n}
            for n, c in enumerate(spec, start=1)]


def tiers(result):
    return [r["priority"] for r in result]


def by_id(result):
    return {r["source_id"]: r for r in result}


class TestCapsAndCascade(unittest.TestCase):
    """The cap arithmetic, driven through the function the writers call.

    These cases were written against an earlier `assign_priorities`, which the
    caps refactor left behind: the production paths moved to
    `rank_population` and nothing called the old function again, so seven
    passing tests were guarding a copy of the rule rather than the rule. The
    tier counts are unchanged; the positions are not, because the population
    sort puts gate-passing rows first rather than preserving the model's order.
    """

    def test_fewer_than_cap_pass_the_gate_tier_is_smaller_never_padded(self):
        out = tiers(rank_population(rows("ggguuuuuuu")))
        self.assertEqual(out[:3], ["high"] * 3)
        # The remaining 7 must NOT be promoted to fill the tier.
        self.assertNotIn("high", out[3:])
        self.assertEqual(out.count("high"), 3)

    def test_no_row_passes_the_gate_high_is_empty_and_all_cascade(self):
        out = tiers(rank_population(rows("u" * 15)))
        self.assertEqual(out.count("high"), 0)
        # Top 10 cascade into medium; the rest fall to low.
        self.assertEqual(out.count("medium"), MEDIUM_CAP)
        self.assertEqual(out.count("low"), 5)

    def test_gated_rows_past_the_cap_cascade_and_crowd_out_the_rest(self):
        # 15 gated rows and 10 un-gated. Ten gated take the top tier; the
        # five that overflow cascade into medium alongside the un-gated
        # leaders, and the tail gets nothing left.
        result = rank_population(rows("u" * 10 + "g" * 15))
        out = tiers(result)
        self.assertEqual(out.count("high"), HIGH_CAP)
        self.assertEqual(out.count("medium"), MEDIUM_CAP)
        self.assertEqual(out.count("low"), 5)
        # Gate-passing rows sort first, so the top tier is entirely gated.
        self.assertTrue(all(r["intent_gated"] for r in result[:HIGH_CAP]))

    def test_the_gate_outranks_the_models_order(self):
        # An un-gated row the model ranked first still loses the top tier to
        # a gated row it ranked second — that is the whole point of the gate.
        result = rank_population(rows("ug"))
        self.assertEqual(tiers(result), ["high", "medium"])
        self.assertEqual([r["source_id"] for r in result], ["i2", "i1"])

    def test_positions_are_contiguous_and_follow_the_population_order(self):
        result = rank_population(rows("ugg"))
        self.assertEqual([r["global_rank"] for r in result], [1, 2, 3])
        # Gated first, then the un-gated row — not the model's order.
        self.assertEqual([r["source_id"] for r in result], ["i2", "i3", "i1"])
        self.assertEqual(tiers(result), ["high", "high", "medium"])

    def test_the_models_order_breaks_ties_within_a_gate_class(self):
        """batch_rank is the tiebreaker, not the primary key."""
        result = rank_population(rows("gg" + "u" * 3))
        self.assertEqual([r["source_id"] for r in result],
                         ["i1", "i2", "i3", "i4", "i5"])

    def test_empty_input(self):
        self.assertEqual(rank_population([]), [])

    def test_exactly_at_both_caps(self):
        out = tiers(rank_population(rows("g" * 10 + "u" * 10)))
        self.assertEqual(out.count("high"), 10)
        self.assertEqual(out.count("medium"), 10)
        self.assertEqual(out.count("low"), 0)


class TestPinsBeatTheGate(unittest.TestCase):
    """A pin is an instruction; the gate is an inference. The instruction wins."""

    def _rows(self, n, gated, pinned=None):
        return [{"source_id": f"m{i}", "intent_gated": i < gated, "batch_rank": i + 1,
                 "manual_priority": (pinned or {}).get(f"m{i}")} for i in range(n)]

    def test_a_pinned_row_takes_the_users_tier_not_the_gates(self):
        got = {r["source_id"]: r["priority"]
               for r in rank_population(self._rows(4, gated=4, pinned={"m0": "low"}))}
        self.assertEqual(got["m0"], "low")
        self.assertEqual(got["m1"], "high")

    def test_a_pinned_row_sorts_by_its_pin(self):
        got = [r["source_id"]
               for r in rank_population(self._rows(3, gated=3, pinned={"m0": "low"}))]
        self.assertEqual(got[-1], "m0")

    def test_a_demoted_row_does_not_consume_a_capped_slot(self):
        """Otherwise a pin costs the tier a place while leaving it."""
        pinned = {f"m{i}": "low" for i in range(5)}
        got = rank_population(self._rows(20, gated=20, pinned=pinned))
        high = [r["source_id"] for r in got if r["priority"] == "high"]
        self.assertEqual(len(high), HIGH_CAP)
        self.assertFalse(set(high) & set(pinned), "a pinned row is holding a high slot")

    def test_a_pin_upward_beats_an_ungated_rows_cascade(self):
        got = {r["source_id"]: r["priority"]
               for r in rank_population(self._rows(3, gated=0, pinned={"m2": "high"}))}
        self.assertEqual(got["m2"], "high")


class TestPinsAreCappedToo(unittest.TestCase):
    """A pin decides the order rows claim a tier, not whether the tier has a size.

    "The ranked list is short by construction" is the property this recipe
    sells. A tier that any number of pins can grow is short only by
    instruction, which is the thing the caps exist to replace.
    """

    def _pinned(self, n, tier="high", prefix="m"):
        return [{"source_id": f"{prefix}{i}", "intent_gated": False,
                 "batch_rank": i + 1, "manual_priority": tier} for i in range(n)]

    def test_more_pins_than_the_tier_holds_overflow_rather_than_widen_it(self):
        got = rank_population(self._pinned(HIGH_CAP + 1))
        tiers = Counter(r["priority"] for r in got)
        self.assertEqual(tiers["high"], HIGH_CAP)
        self.assertEqual(tiers["medium"], 1)

    def test_the_overflowing_pin_is_the_last_one_by_position(self):
        got = rank_population(self._pinned(HIGH_CAP + 1))
        overflowed = [r for r in got if r["priority"] != "high"]
        self.assertEqual([r["source_id"] for r in overflowed], [f"m{HIGH_CAP}"])

    def test_a_repeated_source_id_cannot_widen_a_tier(self):
        """The cap counts places, not names."""
        rows = self._pinned(HIGH_CAP + 4)
        for row in rows[HIGH_CAP:]:
            row["source_id"] = "m0"            # malformed input, same id repeated
        tiers = Counter(r["priority"] for r in rank_population(rows))
        self.assertEqual(tiers["high"], HIGH_CAP)

    def test_pins_take_the_tier_ahead_of_gated_rows(self):
        rows = self._pinned(3) + [
            {"source_id": f"g{i}", "intent_gated": True, "batch_rank": i + 1,
             "manual_priority": None} for i in range(HIGH_CAP)]
        got = {r["source_id"]: r["priority"] for r in rank_population(rows)}
        self.assertTrue(all(got[f"m{i}"] == "high" for i in range(3)))
        # Three pins displaced three gated rows rather than adding to the tier.
        self.assertEqual(sum(1 for v in got.values() if v == "high"), HIGH_CAP)

    def test_a_pin_down_never_claims_a_capped_slot(self):
        rows = ([{"source_id": "down", "intent_gated": True, "batch_rank": 1,
                  "manual_priority": "low"}]
                + [{"source_id": f"g{i}", "intent_gated": True, "batch_rank": i + 2,
                    "manual_priority": None} for i in range(3)])
        got = {r["source_id"]: r["priority"] for r in rank_population(rows)}
        self.assertEqual(got["down"], "low")
        self.assertEqual(sum(1 for v in got.values() if v == "high"), 3)

    def test_the_caps_hold_with_pins_and_gated_rows_mixed_beyond_both(self):
        rows = self._pinned(6) + self._pinned(6, "medium", prefix="q") + [
            {"source_id": f"g{i}", "intent_gated": True, "batch_rank": i + 1,
             "manual_priority": None} for i in range(20)]
        tiers = Counter(r["priority"] for r in rank_population(rows))
        self.assertEqual(tiers["high"], HIGH_CAP)
        self.assertEqual(tiers["medium"], MEDIUM_CAP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
