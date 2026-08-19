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


class TestCorrectionsAreIdempotent(unittest.TestCase):
    """Only a state transition is evidence.

    A retried command, a double-click, or a re-run script is one decision. The
    preference policy counts corrections, so recording a retry three times is
    how three copies of one decision reach the threshold and mint a rule the
    user never asked for.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "ranking", "apply_decisions", "correct", "preferences"):
            sys.modules.pop(m, None)
        import _db, apply_decisions, correct, preferences   # noqa: E402
        self._db, self.correct, self.preferences = _db, correct, preferences
        _db.ensure_store()
        self.db = _db.ledger_path()
        with sqlite3.connect(self.db) as c:
            c.execute(
                "INSERT INTO items(source_id, source, scope, event_at, sender)"
                " VALUES ('m1','email','inbox','2026-08-18T00:00:00Z',"
                "'news@vendor.example')")
        apply_decisions.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1,
             "intent_gated": False, "title": "t"}]})

    def events(self, event_type):
        with sqlite3.connect(self.db) as c:
            return c.execute("SELECT COUNT(*) FROM events"
                             " WHERE actor='user' AND event_type=?",
                             (event_type,)).fetchone()[0]

    def test_repeating_ignore_records_one_correction(self):
        first = self.correct.ignore("m1")
        again = self.correct.ignore("m1")
        self.assertTrue(first["changed"])
        self.assertFalse(again["changed"])
        self.correct.ignore("m1")
        self.assertEqual(self.events("ignored"), 1)

    def test_repeating_unignore_records_one_correction(self):
        self.correct.ignore("m1")
        self.assertTrue(self.correct.unignore("m1")["changed"])
        self.assertFalse(self.correct.unignore("m1")["changed"])
        self.assertEqual(self.events("restored"), 1)

    def test_repinning_the_same_tier_records_one_correction(self):
        self.assertTrue(self.correct.set_priority("m1", "low")["changed"])
        self.assertFalse(self.correct.set_priority("m1", "low")["changed"])
        self.assertEqual(self.events("priority_override"), 1)

    def test_changing_the_pin_to_a_different_tier_does_record_one(self):
        """Idempotency must not swallow a real change of mind."""
        self.correct.set_priority("m1", "low")
        self.assertTrue(self.correct.set_priority("m1", "high")["changed"])
        self.assertEqual(self.events("priority_override"), 2)

    def test_retries_alone_cannot_reach_the_preference_threshold(self):
        for _ in range(self.preferences.THRESHOLD + 2):
            self.correct.ignore("m1")
        with sqlite3.connect(self.db) as c:
            corrections = self.preferences.collect(c)
        self.assertEqual(len(corrections), 1)
        self.assertEqual(self.preferences.candidates(corrections), [])

    def test_unignore_writes_an_event_type_the_schema_accepts(self):
        """It did not, and nothing caught it because nothing called it."""
        self.correct.ignore("m1")
        self.correct.unignore("m1")           # would raise IntegrityError
        with sqlite3.connect(self.db) as c:
            self.assertEqual(
                c.execute("SELECT status FROM obligations").fetchone()[0], "open")


class TestRerankAuditCoversThePopulation(unittest.TestCase):
    """A row can move without this pass mentioning it, and that is the common case.

    A new arrival at the top pushes the tenth row out of the tier. The envelope
    never names that row, so an audit built from the envelope records nothing —
    leaving the store's own history unable to explain why the row moved.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db, apply_decisions             # noqa: E402
        self._db, self.mod = _db, apply_decisions
        _db.ensure_store()
        self.db = _db.ledger_path()

    def _items(self, ids):
        with sqlite3.connect(self.db) as c:
            for sid in ids:
                c.execute("INSERT INTO items(source_id, source, scope, event_at)"
                          " VALUES (?,'email','inbox','2026-08-18T00:00:00Z')", (sid,))

    def _snapshot(self):
        with sqlite3.connect(self.db) as c:
            return {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT source_id, priority, global_rank FROM obligations"
                " WHERE status='open'")}

    def _reranked(self):
        with sqlite3.connect(self.db) as c:
            return c.execute("SELECT COUNT(*) FROM events"
                             " WHERE event_type='reranked'").fetchone()[0]

    def test_every_displaced_row_is_audited_even_when_unmentioned(self):
        self._items([f"a{i}" for i in range(10)])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": f"a{i}", "decision": "CREATE", "rank": i + 1,
             "intent_gated": True, "title": f"a{i}"} for i in range(10)]})
        before, base = self._snapshot(), self._reranked()

        self._items(["b0"])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "b0", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "b0"}]})
        after = self._snapshot()

        moved = {k for k in before if before[k] != after[k]}
        self.assertTrue(moved, "the fixture failed to displace anything")
        self.assertEqual(self._reranked() - base, len(moved))

    def test_the_row_pushed_out_of_the_tier_is_among_them(self):
        self._items([f"a{i}" for i in range(10)])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": f"a{i}", "decision": "CREATE", "rank": i + 1,
             "intent_gated": True, "title": f"a{i}"} for i in range(10)]})
        self._items(["b0"])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "b0", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "b0"}]})
        self.assertEqual(self._snapshot()["a9"], ("medium", 11))
        with sqlite3.connect(self.db) as c:
            row = c.execute(
                "SELECT e.before_json, e.after_json FROM events e"
                " JOIN obligations o ON o.id = e.obligation_id"
                " WHERE o.source_id='a9' AND e.event_type='reranked'").fetchone()
        self.assertIsNotNone(row, "the displaced row has no rerank event")
        self.assertEqual(json.loads(row[0]), {"priority": "high", "rank": 10})
        self.assertEqual(json.loads(row[1]), {"priority": "medium", "rank": 11})

    def test_a_row_created_by_this_envelope_is_not_also_audited_as_reranked(self):
        self._items(["a0"])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "a0", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "a0"}]})
        self.assertEqual(self._reranked(), 0)

    def test_an_unchanged_population_writes_no_events(self):
        self._items(["a0"])
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "a0", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "a0"}]})
        base = self._reranked()
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "a0", "decision": "KEEP_OPEN", "rank": 1,
             "intent_gated": True, "title": "a0"}]})
        self.assertEqual(self._reranked(), base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
