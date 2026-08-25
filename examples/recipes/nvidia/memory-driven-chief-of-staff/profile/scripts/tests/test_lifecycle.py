# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Retention, exclusion, export and reset.

These are the controls a person exercises over their own data, so the tests ask
the questions that person would: is the text actually gone, is the history
still readable, did the excluded message really never arrive, and did the reset
leave anything behind.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import exclusions  # noqa: E402
import export_store  # noqa: E402
import reset  # noqa: E402
import retention  # noqa: E402
from normalize import insert_items  # noqa: E402

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")


def iso(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        # `_db` refuses a directory that does not look like a profile home, so
        # a marker is what makes this a store rather than a guess at one.
        (Path(self.home) / "distribution.yaml").write_text("id: test\n",
                                                          encoding="utf-8")
        self.workspace = Path(self.home) / "workspace"
        (self.workspace / "ledger").mkdir(parents=True)
        self.db = self.workspace / "ledger" / "state.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
        os.environ["HERMES_HOME"] = self.home

    def tearDown(self):
        for name in ("RETENTION_DAYS",):
            os.environ.pop(name, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def add(self, source_id, *, days_ago=0, body="hello", sender="Dana",
            scope="inbox", source="email"):
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO items(source_id, source, scope, event_at, sender,"
                " subject, body, state) VALUES (?,?,?,?,?,?,?, 'pending')",
                (source_id, source, scope, iso(days_ago), sender,
                 f"about {source_id}", body))

    def item(self, source_id):
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM items WHERE source_id=?",
                               (source_id,)).fetchone()
        return dict(row) if row else None


class TestRetentionClearsTextAndKeepsHistory(StoreCase):
    """The record of a decision outlives the message that prompted it.

    A store that judges what arrives has no reason to hold the text
    indefinitely; what stays useful is who wrote, when, and what was decided.
    """

    def test_an_old_body_is_cleared(self):
        self.add("old", days_ago=90)
        retention.main([])
        self.assertIsNone(self.item("old")["body"])

    def test_a_recent_body_is_left_alone(self):
        self.add("fresh", days_ago=1)
        retention.main([])
        self.assertEqual(self.item("fresh")["body"], "hello")

    def test_the_metadata_survives_the_clearing(self):
        """Otherwise history stops being inspectable, which is the whole point."""
        self.add("old", days_ago=90)
        retention.main([])
        row = self.item("old")
        self.assertEqual(row["sender"], "Dana")
        self.assertEqual(row["subject"], "about old")
        self.assertTrue(row["event_at"])
        self.assertEqual(row["state"], "pending")

    def test_a_cleared_body_is_distinguishable_from_one_that_never_existed(self):
        self.add("had_text", days_ago=90)
        self.add("never_had_text", days_ago=90, body=None)
        retention.main([])
        self.assertIsNotNone(self.item("had_text")["body_cleared_at"])
        self.assertIsNone(self.item("never_had_text")["body_cleared_at"])

    def test_the_window_is_configurable(self):
        self.add("week_old", days_ago=8)
        os.environ["RETENTION_DAYS"] = "7"
        retention.main([])
        self.assertIsNone(self.item("week_old")["body"])

    def test_a_window_that_would_clear_everything_is_refused(self):
        for bad in ("0", "-1", "abc"):
            os.environ["RETENTION_DAYS"] = bad
            with self.assertRaises(SystemExit):
                retention.main([])

    def test_a_window_beyond_the_upper_bound_is_refused(self):
        """Documented as 1..3650; a number outside it must not pass silently."""
        os.environ["RETENTION_DAYS"] = str(retention.MAX_RETENTION_DAYS + 1)
        with self.assertRaises(SystemExit):
            retention.main([])

    def test_the_default_window_is_the_one_the_docs_state(self):
        """The README and docs/data-lifecycle.md both say thirty days."""
        self.assertEqual(retention.RETENTION_DAYS, 30)
        self.add("just_inside", days_ago=29)
        self.add("just_outside", days_ago=31)
        retention.main([])
        self.assertEqual(self.item("just_inside")["body"], "hello")
        self.assertIsNone(self.item("just_outside")["body"])

    def test_dry_run_changes_nothing(self):
        self.add("old", days_ago=90)
        retention.main(["--dry-run"])
        self.assertEqual(self.item("old")["body"], "hello")

    def test_a_second_pass_does_not_re_clear(self):
        self.add("old", days_ago=90)
        retention.main([])
        first = self.item("old")["body_cleared_at"]
        retention.main([])
        self.assertEqual(self.item("old")["body_cleared_at"], first)


class TestExclusionHappensBeforeAnythingIsWritten(StoreCase):
    """Filtering at display leaves the text on disk, which is no use at all.

    Applied in `insert_items` so every writer inherits it — the fixture loader,
    the Slack collector when it lands, and anything written afterwards.
    """

    def write_rules(self, **rules):
        (self.workspace / exclusions.RULES_FILE).write_text(
            json.dumps(rules), encoding="utf-8")

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return [r[0] for r in conn.execute("SELECT source_id FROM items")]

    def insert(self, items):
        with sqlite3.connect(self.db) as conn:
            insert_items(conn, items)

    def item(self, **over):
        base = {"source_id": "m1", "source": "email", "scope": "inbox",
                "event_at": iso(0), "sender": "Dana", "subject": "s",
                "body": "text", "addressing": "direct"}
        base.update(over)
        return base

    def test_an_excluded_sender_never_reaches_the_store(self):
        self.write_rules(senders=["recruiter@agency.example"])
        self.insert([self.item(sender="recruiter@agency.example")])
        self.assertEqual(self.rows(), [])

    def test_an_excluded_domain_never_reaches_the_store(self):
        self.write_rules(domains=["agency.example"])
        self.insert([self.item(sender="anyone@agency.example")])
        self.assertEqual(self.rows(), [])

    def test_an_excluded_channel_never_reaches_the_store(self):
        self.write_rules(channels=["C0SALARY01"])
        self.insert([self.item(scope="C0SALARY01", source="slack")])
        self.assertEqual(self.rows(), [])

    def test_a_sender_can_be_excluded_by_source_id(self):
        """A display name is something the other person can change."""
        self.write_rules(senders=["u01recruit"])
        self.insert([self.item(sender="Friendly Name", sender_id="U01RECRUIT")])
        self.assertEqual(self.rows(), [])

    def test_matching_ignores_case(self):
        self.write_rules(senders=["Recruiter@Agency.Example"])
        self.insert([self.item(sender="recruiter@AGENCY.example")])
        self.assertEqual(self.rows(), [])

    def test_everything_else_still_arrives(self):
        self.write_rules(senders=["recruiter@agency.example"])
        self.insert([self.item(source_id="keep", sender="Dana")])
        self.assertEqual(self.rows(), ["keep"])

    def test_no_rules_means_no_filtering(self):
        self.insert([self.item()])
        self.assertEqual(self.rows(), ["m1"])

    def test_an_unreadable_rules_file_does_not_stop_the_intake(self):
        """A typo here must not silently halt collection."""
        (self.workspace / exclusions.RULES_FILE).write_text("{ not json")
        self.insert([self.item()])
        self.assertEqual(self.rows(), ["m1"])

    def test_a_pattern_is_not_a_glob(self):
        """Documented as exact. A wildcard that matched would exclude far more
        than intended, and say nothing about having done so."""
        self.write_rules(domains=["*.example"])
        self.insert([self.item(source_id="keep", sender="dana@agency.example")])
        self.assertEqual(self.rows(), ["keep"])

    def test_the_report_counts_what_was_dropped(self):
        """`exclusions: N message(s) not stored` — the count, never the text."""
        self.write_rules(senders=["dana"])
        kept, dropped = exclusions.partition(
            [self.item(source_id="a"), self.item(source_id="b"),
             self.item(source_id="c", sender="Sam")])
        self.assertEqual(dropped, 2)
        self.assertEqual([i["source_id"] for i in kept], ["c"])

    def test_a_drop_is_reported_rather_than_silent(self):
        self.write_rules(senders=["dana"])
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "import sqlite3\n"
            "from normalize import insert_items\n"
            "conn = sqlite3.connect(%r)\n"
            "insert_items(conn, [%r])\n" % (str(HERE), str(self.db), self.item())
        )
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True,
                              env={**os.environ, "HERMES_HOME": self.home})
        self.assertIn("exclusions", proc.stderr)


class TestExportShowsEverythingItHolds(StoreCase):
    def test_it_writes_both_a_readable_and_a_machine_form(self):
        self.add("m1")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        self.assertTrue((destination / "store.md").exists())
        self.assertTrue((destination / "store.json").exists())

    def test_the_readable_form_contains_the_message(self):
        self.add("m1", body="the cutover window is Thursday")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        text = (destination / "store.md").read_text(encoding="utf-8")
        self.assertIn("cutover window", text)

    def test_a_cleared_body_is_shown_as_cleared_rather_than_missing(self):
        self.add("old", days_ago=90)
        retention.main([])
        destination = Path(self.home) / "out"
        export_store.export(destination)
        text = (destination / "store.md").read_text(encoding="utf-8")
        self.assertIn("text cleared", text)

    def test_the_learned_policy_travels_with_it(self):
        """Documented as copied whole; it is as much about the user as the memory."""
        policy = self.workspace / "policy"
        policy.mkdir(exist_ok=True)
        (policy / "preferences.md").write_text("ignores: newsletters\n",
                                               encoding="utf-8")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        self.assertTrue((destination / "policy" / "preferences.md").exists())

    def test_the_memory_travels_with_it(self):
        memory = self.workspace / "memory" / "people"
        memory.mkdir(parents=True)
        (memory / "dana.md").write_text("name: Dana\n", encoding="utf-8")
        destination = Path(self.home) / "out"
        report = export_store.export(destination)
        self.assertEqual(report["memory_pages"], 1)
        self.assertTrue((destination / "memory" / "people" / "dana.md").exists())


class TestResetLeavesNothingBehind(StoreCase):
    """A partial reset is worse than none: it answers the question wrongly."""

    def populate(self):
        self.add("m1")
        (self.workspace / "memory").mkdir(exist_ok=True)
        (self.workspace / "memory" / "index.md").write_text("x", encoding="utf-8")
        (self.workspace / "policy").mkdir(exist_ok=True)
        (self.workspace / "policy" / "preferences.md").write_text("y", encoding="utf-8")

    def test_it_refuses_without_consent(self):
        self.populate()
        self.assertEqual(reset.main([]), 1)
        self.assertTrue(self.db.exists())

    def test_dry_run_reports_and_removes_nothing(self):
        self.populate()
        self.assertEqual(reset.main(["--dry-run"]), 0)
        self.assertTrue(self.db.exists())
        self.assertTrue((self.workspace / "memory").exists())

    def test_it_removes_the_store_the_memory_and_the_policy(self):
        self.populate()
        self.assertEqual(reset.main(["--yes"]), 0)
        self.assertFalse(self.db.exists())
        self.assertFalse((self.workspace / "memory").exists())
        self.assertFalse((self.workspace / "policy").exists())

    def test_the_learned_policy_is_not_forgotten_in_the_sweep(self):
        """It encodes what the user ignores, which is about them."""
        self.assertIn("policy", reset.targets())

    def test_the_collection_bookkeeping_goes_too(self):
        """Left behind, the next run re-reads windows the user just cleared."""
        self.assertIn("collection_state", reset.targets())

    def test_a_partial_removal_does_not_report_success(self):
        """A reset that half worked must not read as one that worked."""
        self.populate()
        target = reset.targets()["memory"]
        original = reset.shutil.rmtree

        def refuse(path, *a, **kw):
            if Path(path) == target:
                raise OSError(13, "Permission denied")
            return original(path, *a, **kw)

        reset.shutil.rmtree = refuse
        try:
            self.assertEqual(reset.main(["--yes"]), 1)
        finally:
            reset.shutil.rmtree = original

    def test_it_says_the_credential_is_somewhere_else(self):
        """Somebody withdrawing consent wants both, and would stop after one."""
        self.populate()
        script = ("import sys; sys.path.insert(0, %r)\n"
                  "import reset\nraise SystemExit(reset.main(['--yes']))"
                  % str(HERE))
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True,
                              env={**os.environ, "HERMES_HOME": self.home})
        self.assertIn("provider delete", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
