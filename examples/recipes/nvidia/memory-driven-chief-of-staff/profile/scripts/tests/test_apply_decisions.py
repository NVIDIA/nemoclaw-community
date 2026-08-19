# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end: envelope in, rows and audit events out, one transaction."""

import json, os, sqlite3, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


class TestApply(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db, apply_decisions           # noqa: E402
        self._db, self.mod = _db, apply_decisions
        _db.ensure_store()
        self.db = _db.ledger_path()
        with sqlite3.connect(self.db) as c:
            for n in range(1, 4):
                c.execute(
                    "INSERT INTO items(source_id, source, scope, event_at, subject, body)"
                    " VALUES (?,'email','inbox','2026-08-18T00:00:00Z',?,?)",
                    (f"m{n}", f"subject {n}", f"body {n}"))

    def q(self, sql, *a):
        with sqlite3.connect(self.db) as c:
            return c.execute(sql, a).fetchall()

    def test_create_updates_items_writes_audit_and_advances_cursor(self):
        self.mod.apply({
            "version": 1, "pass": "intake",
            "decisions": [
                {"source_id": "m1", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "Reply to capacity thread",
                 "kind": "response", "est_effort": "minutes"},
                {"source_id": "m2", "decision": "SKIP"},
            ],
            "cursor": {"source": "email", "scope": "inbox", "value": "delta-1"},
        })
        self.assertEqual(self.q("SELECT priority, intent_gated FROM obligations"),
                         [("high", 1)])
        self.assertEqual(self.q("SELECT state FROM items WHERE source_id='m1'"), [("judged",)])
        self.assertEqual(self.q("SELECT state FROM items WHERE source_id='m2'"), [("skipped",)])
        self.assertEqual(self.q("SELECT event_type, actor FROM events"), [("created", "agent")])
        self.assertEqual(self.q("SELECT cursor FROM cursors"), [("delta-1",)])

    def test_rerank_is_audited_and_manual_priority_is_never_cleared(self):
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "t"}]})
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE obligations SET manual_priority='low'")
        # Second pass: the row loses the gate, so it drops out of the top tier.
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "KEEP_OPEN", "rank": 1,
             "intent_gated": False, "title": "t"}]})
        # The effective tier is the pinned one. A correction the ranking
        # acknowledges but does not act on is not a correction.
        self.assertEqual(self.q("SELECT priority, manual_priority FROM obligations"),
                         [("low", "low")])
        self.assertEqual([r[0] for r in self.q("SELECT event_type FROM events ORDER BY id")],
                         ["created", "reranked"])

    def test_mark_done_closes_without_touching_the_tier(self):
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "t"}]})
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "MARK_DONE"}]})
        self.assertEqual(self.q("SELECT status, priority FROM obligations"), [("done", "high")])

    def test_mark_done_persists_the_closing_reason_so_it_can_be_audited(self):
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "t", "urgency_reason": "due Friday"}]})
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "MARK_DONE",
             "urgency_reason": "replied on the thread 2 days ago"}]})
        self.assertEqual(self.q("SELECT urgency_reason FROM obligations"),
                         [("replied on the thread 2 days ago",)])
        after = self.q("SELECT after_json FROM events WHERE event_type='completed'")[0][0]
        self.assertIn("replied on the thread", after)

    def test_two_rows_claiming_the_same_rank_are_rejected(self):
        # The caps make position consequential, so resolving a tie by input
        # order would silently pick a winner the model never chose.
        with self.assertRaises(ValueError):
            self.mod.apply({"version": 1, "decisions": [
                {"source_id": "m1", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "a"},
                {"source_id": "m2", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "b"}]})
        self.assertEqual(self.q("SELECT count(*) FROM obligations"), [(0,)])

    def test_bad_envelope_is_rejected_and_writes_nothing(self):
        for bad in (
            {"version": 2, "decisions": []},
            {"version": 1, "decisions": [{"source_id": "m1", "decision": "NOPE"}]},
            {"version": 1, "decisions": [{"source_id": "m1", "decision": "CREATE",
                                          "rank": "one", "intent_gated": True, "title": "t"}]},
            {"version": 1, "decisions": [{"source_id": "m1", "decision": "CREATE", "rank": 1,
                                          "intent_gated": True, "title": "t",
                                          "kind": "both"}]},
            {"version": 1, "decisions": [{"source_id": "m1", "decision": "SKIP"},
                                         {"source_id": "m1", "decision": "SKIP"}]},
        ):
            with self.assertRaises(ValueError):
                self.mod.apply(bad)
        self.assertEqual(self.q("SELECT count(*) FROM obligations"), [(0,)])
        self.assertEqual(self.q("SELECT count(*) FROM events"), [(0,)])

    def test_failure_mid_envelope_rolls_back_everything(self):
        # m9 does not exist, so the obligations FK fires partway through.
        with self.assertRaises(sqlite3.IntegrityError):
            self.mod.apply({"version": 1, "decisions": [
                {"source_id": "m1", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "ok"},
                {"source_id": "m9", "decision": "CREATE", "rank": 2,
                 "intent_gated": True, "title": "orphan"}],
                "cursor": {"source": "email", "scope": "inbox", "value": "must-not-land"}})
        self.assertEqual(self.q("SELECT count(*) FROM obligations"), [(0,)])
        self.assertEqual(self.q("SELECT count(*) FROM cursors"), [(0,)])


class TestCapsAcrossBatches(unittest.TestCase):
    """The caps bound the open population, not one envelope.

    Ranking within an envelope is what a batch-local implementation does, and
    it is wrong in a way that only shows up on the second run: two twenty-row
    batches each keep their own top ten, so the store ends up with twenty rows
    at the top tier and two rows claiming every rank.
    """

    BATCH = 20

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db, apply_decisions           # noqa: E402
        self._db, self.mod = _db, apply_decisions
        _db.ensure_store()
        self.db = _db.ledger_path()

    def _batch(self, prefix, gated=0):
        """One envelope of BATCH rows; the first `gated` of them are gated."""
        with sqlite3.connect(self.db) as c:
            for n in range(self.BATCH):
                c.execute(
                    "INSERT INTO items(source_id, source, scope, event_at, subject, body)"
                    " VALUES (?,'email','inbox','2026-08-18T00:00:00Z',?,'body')",
                    (f"{prefix}{n}", f"subject {n}"))
        self.mod.apply({"version": 1, "pass": "intake", "decisions": [
            {"source_id": f"{prefix}{n}", "decision": "CREATE", "rank": n + 1,
             "intent_gated": n < gated, "title": f"t{n}"}
            for n in range(self.BATCH)]})

    def q(self, sql, *a):
        with sqlite3.connect(self.db) as c:
            return c.execute(sql, a).fetchall()

    def test_two_batches_keep_one_set_of_caps_and_unique_ranks(self):
        # Fourteen rows pass the gate across the two batches, which is more
        # than the high tier holds. A batch-local cap would admit all of them,
        # six then eight, because neither batch exceeds the cap on its own.
        self._batch("a", gated=6)
        self._batch("b", gated=8)

        counts = dict(self.q("SELECT priority, COUNT(*) FROM obligations"
                             " WHERE status='open' GROUP BY priority"))
        self.assertEqual(counts.get("high"), 10)
        self.assertEqual(counts.get("medium"), 10)
        self.assertEqual(counts.get("low"), 2 * self.BATCH - 20)

        ranks = [r[0] for r in self.q(
            "SELECT global_rank FROM obligations WHERE status='open'")]
        self.assertEqual(len(ranks), len(set(ranks)), "global_rank is not unique")
        self.assertEqual(sorted(ranks), list(range(1, 2 * self.BATCH + 1)))

    def test_a_later_gated_row_displaces_an_earlier_ungated_one(self):
        """Re-ranking is global, so batch two can take the top tier from batch one."""
        self._batch("a")                       # nothing gated
        self._batch("b", gated=self.BATCH)     # every row gated

        top = {r[0] for r in self.q(
            "SELECT source_id FROM obligations WHERE priority='high'")}
        self.assertTrue(all(s.startswith("b") for s in top), sorted(top))

    def test_an_ungated_population_leaves_the_high_tier_empty(self):
        """The high tier is drawn only from gated rows, and is never padded.

        This is the reservation the recipe is built on: the top tier belongs to
        what the user chose, so forty ungated rows produce no high tier at all
        rather than a top ten of whatever arrived.
        """
        self._batch("a")
        self._batch("b")
        counts = dict(self.q("SELECT priority, COUNT(*) FROM obligations"
                             " WHERE status='open' GROUP BY priority"))
        self.assertIsNone(counts.get("high"))
        self.assertEqual(counts.get("medium"), 10)
        self.assertEqual(counts.get("low"), 2 * self.BATCH - 10)

    def test_the_database_itself_refuses_a_duplicate_rank(self):
        """The cap logic is backed by a constraint, not only by the writer."""
        self._batch("a")
        with sqlite3.connect(self.db) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE obligations SET global_rank=1 WHERE source_id='a5'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
