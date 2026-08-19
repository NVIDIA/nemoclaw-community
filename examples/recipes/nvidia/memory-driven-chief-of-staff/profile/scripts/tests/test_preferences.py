# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: bounded preference updates."""

import sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from preferences import MAX_POLICY_ENTRIES, THRESHOLD, cap, candidates  # noqa: E402


def corr(n, sender="ci@build.example.com", event="ignored", source="email", kind="action"):
    return [{"event_type": event, "sender": sender, "source": source, "kind": kind}
            for _ in range(n)]


class TestPreferences(unittest.TestCase):

    def test_below_the_threshold_nothing_qualifies(self):
        self.assertEqual(candidates(corr(THRESHOLD - 1)), [])

    def test_at_the_threshold_a_preference_qualifies(self):
        got = candidates(corr(THRESHOLD))
        self.assertTrue(got)
        self.assertEqual(got[0].count, THRESHOLD)

    def test_counts_do_not_merge_across_distinct_senders(self):
        # Two senders with two corrections each must not add up to one sender
        # with four. They do still aggregate at the coarser source/kind
        # dimension, which is intended and asserted separately below — the
        # earlier version of this test filtered that result out and read as a
        # stronger guarantee than it was.
        mixed = corr(2, sender="a@x.example.com") + corr(2, sender="b@y.example.com")
        self.assertEqual([c for c in candidates(mixed) if c.dimension == "sender"], [])

    def test_volume_across_senders_does_aggregate_at_the_coarser_dimension(self):
        # Stated plainly because it is a real property of the design: four
        # corrections over two sub-threshold senders qualify as a source/kind
        # preference. That is deliberate — "everything from email that asks for
        # an action gets ignored" is a real preference — but it means volume
        # alone can clear the bar at that dimension, and the policy sentence
        # the skill writes has to say which dimension it is about.
        mixed = corr(2, sender="a@x.example.com") + corr(2, sender="b@y.example.com")
        coarse = [c for c in candidates(mixed) if c.dimension == "source_kind"]
        self.assertEqual(len(coarse), 1)
        self.assertEqual(coarse[0].count, 4)

    def test_a_shared_domain_qualifies_even_when_no_single_sender_does(self):
        mixed = (corr(2, sender="build1@ci.example.com")
                 + corr(2, sender="build2@ci.example.com"))
        domains = [c for c in candidates(mixed) if c.dimension == "domain"]
        self.assertEqual(len(domains), 1)
        self.assertEqual(domains[0].value, "ci.example.com")
        self.assertEqual(domains[0].count, 4)

    def test_the_dominant_correction_type_is_reported(self):
        rows = corr(3, event="priority_override")
        self.assertEqual(candidates(rows)[0].event_type, "priority_override")

    def test_results_are_ordered_by_strength(self):
        rows = corr(5, sender="a@x.example.com") + corr(3, sender="b@y.example.com")
        counts = [c.count for c in candidates(rows)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_the_policy_is_capped(self):
        entries = [f"- entry {n}" for n in range(MAX_POLICY_ENTRIES + 10)]
        kept = cap(entries)
        self.assertEqual(len(kept), MAX_POLICY_ENTRIES)
        self.assertEqual(kept[0], entries[0], "newest first, oldest dropped")

    def test_a_correction_with_no_sender_still_groups_by_source(self):
        rows = [{"event_type": "ignored", "sender": None,
                 "source": "slack", "kind": "response"} for _ in range(THRESHOLD)]
        got = candidates(rows)
        self.assertEqual([c.dimension for c in got], ["source_kind"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
