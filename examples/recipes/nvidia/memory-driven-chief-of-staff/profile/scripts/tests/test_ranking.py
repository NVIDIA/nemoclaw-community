# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Edge cases for the cap-and-cascade arithmetic. No model, no tokens."""

import sys, unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
