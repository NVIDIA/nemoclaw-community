# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Edge cases for the cap-and-cascade arithmetic. No model, no tokens."""

import sys, unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ranking import HIGH_CAP, MEDIUM_CAP, RankedRow, assign_priorities, rank_population  # noqa: E402


def rows(spec):
    """spec is a string of g/u — g = passes the intent gate, u = does not."""
    return [RankedRow(source_id=f"i{n}", intent_gated=(c == "g"))
            for n, c in enumerate(spec, start=1)]


def tiers(result):
    return [r.priority for r in result]


class TestCapsAndCascade(unittest.TestCase):

    def test_fewer_than_cap_pass_the_gate_tier_is_smaller_never_padded(self):
        # 3 gated rows sit at positions 1-3, then 7 un-gated.
        out = assign_priorities(rows("ggguuuuuuu"))
        self.assertEqual(tiers(out)[:3], ["high"] * 3)
        # The remaining 7 must NOT be promoted to fill the tier.
        self.assertNotIn("high", tiers(out)[3:])
        self.assertEqual(tiers(out).count("high"), 3)

    def test_no_row_passes_the_gate_high_is_empty_and_all_cascade(self):
        out = assign_priorities(rows("u" * 15))
        self.assertEqual(tiers(out).count("high"), 0)
        # Top 10 cascade into medium; the rest fall to low.
        self.assertEqual(tiers(out).count("medium"), MEDIUM_CAP)
        self.assertEqual(tiers(out).count("low"), 5)

    def test_cascade_overflow_crowds_genuine_medium_candidates_out(self):
        # 10 un-gated rows rank ahead of 15 others. They cascade into the
        # medium pool and consume it entirely, pushing the rest to low.
        out = assign_priorities(rows("u" * 10 + "g" * 15))
        t = tiers(out)
        # The 15 gated rows start at position 11, so only 10 reach high.
        self.assertEqual(t.count("high"), HIGH_CAP)
        self.assertEqual(t[10:20], ["high"] * 10)
        # The 10 un-gated leaders take the whole medium tier.
        self.assertEqual(t[:10], ["medium"] * 10)
        # Gated rows that ranked below the high cap get nothing left.
        self.assertEqual(t[20:], ["low"] * 5)

    def test_gate_beats_rank_order_for_the_high_tier(self):
        # An un-gated row ranked first still loses the top tier to a gated
        # row ranked second — that is the whole point of the gate.
        out = assign_priorities(rows("ug"))
        self.assertEqual(tiers(out), ["medium", "high"])

    def test_global_rank_records_the_models_order_not_the_tier(self):
        out = assign_priorities(rows("ugg"))
        self.assertEqual([r.global_rank for r in out], [1, 2, 3])
        self.assertEqual(tiers(out), ["medium", "high", "high"])

    def test_empty_input(self):
        self.assertEqual(assign_priorities([]), [])

    def test_exactly_at_both_caps(self):
        out = assign_priorities(rows("g" * 10 + "u" * 10))
        t = tiers(out)
        self.assertEqual(t.count("high"), 10)
        self.assertEqual(t.count("medium"), 10)
        self.assertEqual(t.count("low"), 0)


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
