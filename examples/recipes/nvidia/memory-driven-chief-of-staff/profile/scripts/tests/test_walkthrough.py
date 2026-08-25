# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: the fixture walkthrough, and the claims it makes on screen.

The walkthrough is documentation that executes, which is the only kind worth
shipping — but it is only worth shipping while its narration is still true.
Each claim it prints is asserted here against the store it produced.
"""

import io, contextlib, os, sqlite3, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

FIXTURES = HERE.parents[1] / "fixtures"


class TestWalkthrough(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = cls.tmp
        for m in ("_db", "ranking", "apply_decisions", "correct",
                  "load_fixtures", "walkthrough", "preferences", "memory_check"):
            sys.modules.pop(m, None)
        import _db, walkthrough                # noqa: E402
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cls.rc = walkthrough.main(["--fixtures", str(FIXTURES)])
        cls.output = buffer.getvalue()
        cls.db = _db.ledger_path()

    def rows(self, sql, *a):
        with sqlite3.connect(self.db) as c:
            return c.execute(sql, a).fetchall()

    def test_it_runs_clean(self):
        self.assertEqual(self.rc, 0)

    def test_the_gate_bounds_the_top_tier_rather_than_the_cap(self):
        """Three fixture rows pass the gate, so the top tier holds at most three.

        The cap is ten. If the tier ever fills to it here, the gate has stopped
        being load-bearing and the example's central claim is empty.
        """
        high = self.rows("SELECT source_id FROM obligations"
                         " WHERE status='open' AND priority='high'")
        self.assertLessEqual(len(high), 3)
        self.assertGreater(len(high), 0)

    def test_loud_urgency_that_matches_nothing_chosen_stays_out_of_the_top(self):
        got = self.rows("SELECT priority FROM obligations WHERE source_id=?",
                        "msg-urgent-not-chosen")
        self.assertEqual(got, [("medium",)])

    def test_the_pin_decided_the_tier_and_survived_the_later_pass(self):
        got = self.rows("SELECT priority, manual_priority, status FROM obligations"
                        " WHERE source_id=?", "msg-quiet-decay")
        self.assertEqual(got, [("low", "low", "open")])

    def test_the_ignored_row_left_the_open_list(self):
        got = self.rows("SELECT status FROM obligations WHERE source_id=?", "msg-cc-only")
        self.assertEqual(got, [("ignored",)])

    def test_positions_are_unique_and_contiguous(self):
        ranks = sorted(r[0] for r in self.rows(
            "SELECT global_rank FROM obligations WHERE status='open'"))
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_both_corrections_are_attributed_to_the_user(self):
        got = self.rows("SELECT event_type FROM events WHERE actor='user' ORDER BY id")
        self.assertEqual([r[0] for r in got], ["priority_override", "ignored"])

    def test_no_correction_was_attributed_to_the_agent(self):
        """preference-update reads only user rows; agent-authored ones would poison it."""
        got = self.rows("SELECT COUNT(*) FROM events"
                        " WHERE actor='agent' AND event_type IN ('ignored','priority_override')")
        self.assertEqual(got, [(0,)])

    def test_it_says_which_part_is_canned(self):
        self.assertIn("stands in", self.output)
        self.assertIn("intake.json", self.output)

    def test_it_demonstrates_the_check_failing(self):
        """A verification step that can only pass demonstrates nothing."""
        self.assertIn("people page has no name", self.output)


    def test_it_shows_the_top_tier_emptying_without_the_gate(self):
        """The reservation is the claim; the contrast is the only place it shows.

        The gate verdicts are part of the recorded turn, so this run cannot
        show the memory producing them. It can show what they buy, by ranking
        the same rows again with the verdicts withheld.
        """
        self.assertIn("tiers without the gate: high=0", self.output)

    def test_it_discloses_that_the_gate_verdict_is_recorded(self):
        """Not disclosing it would let a reader think the memory was read."""
        self.assertIn("Deleting the seed memory does not change the tiers",
                      self.output)

    def test_it_discloses_both_recorded_turns(self):
        """The walkthrough records two, and said for a while that it recorded one."""
        self.assertIn("intake.json", self.output)
        self.assertIn("the other recorded turn", self.output)


    def test_it_scopes_the_seed_memory_claim_to_the_tiers(self):
        """Deleting the memory does change step 7; only the tiers are unaffected."""
        self.assertIn("does not change the tiers", self.output)


class TestWalkthroughRefusesASecondRun(unittest.TestCase):
    """A second run inherits the first run's corrections.

    The commentary is written for a first run, so re-running against the same
    profile home printed "the top tier holds three" directly above a table
    showing two. Refusing is better than narrating numbers that are not there.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "ranking", "apply_decisions", "correct",
                  "load_fixtures", "walkthrough", "preferences", "memory_check"):
            sys.modules.pop(m, None)
        import walkthrough                      # noqa: E402
        self.mod = walkthrough

    def _run(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.mod.main(["--fixtures", str(FIXTURES)])
        return code, buffer.getvalue()

    def test_the_first_run_succeeds_and_the_second_refuses(self):
        first, _ = self._run()
        self.assertEqual(first, 0)
        second, output = self._run()
        self.assertEqual(second, 2)
        self.assertIn("already holds", output)
        self.assertIn("HERMES_HOME", output)

    def test_the_refusal_does_not_narrate_a_first_run(self):
        self._run()
        _, output = self._run()
        self.assertNotIn("the top tier holds three", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
