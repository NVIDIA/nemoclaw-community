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
from normalize import (  # noqa: E402
    graph_message_to_item, insert_items, slack_message_to_item)

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

    def test_the_documented_persistent_path_is_the_env_file(self):
        """`cron create` takes no environment, so a shell export changes the
        run you are watching and nothing scheduled after it.

        Measured on Hermes 0.19.0: a line in `$HERMES_HOME/.env` reaches the
        cron subprocess. This pins the documentation to that mechanism so the
        two cannot drift apart silently — the failure being that somebody sets
        the window, never checks, and the nightly pass keeps using thirty days.
        """
        docs = (HERE.parents[1] / "docs" / "data-lifecycle.md").read_text(
            encoding="utf-8")
        self.assertIn("config env-path", docs)
        self.assertIn("RETENTION_DAYS", docs)
        module = (HERE / "retention.py").read_text(encoding="utf-8")
        self.assertIn("env-path", module)

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

    def test_a_malformed_rules_file_stops_the_insert(self):
        """Fail closed. The guarantee is that excluded content is never
        written, and continuing without the rules breaches it silently."""
        (self.workspace / exclusions.RULES_FILE).write_text("{ not json")
        with self.assertRaises(exclusions.ExclusionsUnreadable):
            self.insert([self.item()])
        self.assertEqual(self.rows(), [])

    def test_the_refusal_says_which_file_and_where(self):
        """A stalled intake with no explanation is its own failure."""
        (self.workspace / exclusions.RULES_FILE).write_text("{ not json")
        with self.assertRaises(exclusions.ExclusionsUnreadable) as caught:
            self.insert([self.item()])
        message = str(caught.exception)
        self.assertIn(exclusions.RULES_FILE, message)
        self.assertIn("Nothing has been stored", message)

    def test_a_rules_file_of_the_wrong_shape_stops_the_insert(self):
        (self.workspace / exclusions.RULES_FILE).write_text('["dana"]')
        with self.assertRaises(exclusions.ExclusionsUnreadable):
            self.insert([self.item()])
        self.assertEqual(self.rows(), [])

    def test_a_rule_key_of_the_wrong_type_stops_the_insert(self):
        """`{"senders": "dana"}` reads as a list of characters otherwise."""
        (self.workspace / exclusions.RULES_FILE).write_text(
            '{"senders": "dana"}')
        with self.assertRaises(exclusions.ExclusionsUnreadable):
            self.insert([self.item()])
        self.assertEqual(self.rows(), [])

    def test_a_misspelled_key_stops_the_insert(self):
        """`{"sender": [...]}` parsed cleanly, matched nothing, and read as a
        working rule — the exact failure fail-closed exists to prevent."""
        (self.workspace / exclusions.RULES_FILE).write_text(
            json.dumps({"sender": ["Dana"]}), encoding="utf-8")
        with self.assertRaises(exclusions.ExclusionsUnreadable) as caught:
            self.insert([self.item()])
        self.assertIn("sender", str(caught.exception))
        self.assertEqual(self.rows(), [])

    def test_a_key_alongside_the_documented_ones_stops_the_insert(self):
        (self.workspace / exclusions.RULES_FILE).write_text(
            json.dumps({"senders": ["dana"], "sendrs": ["sam"]}),
            encoding="utf-8")
        with self.assertRaises(exclusions.ExclusionsUnreadable):
            self.insert([self.item()])
        self.assertEqual(self.rows(), [])

    def test_a_non_string_rule_stops_the_insert(self):
        """`123` used to become the rule "123", which matches nothing."""
        (self.workspace / exclusions.RULES_FILE).write_text(
            json.dumps({"senders": [123]}), encoding="utf-8")
        with self.assertRaises(exclusions.ExclusionsUnreadable) as caught:
            self.insert([self.item()])
        self.assertIn("123", str(caught.exception))
        self.assertEqual(self.rows(), [])

    def test_the_documented_keys_are_all_accepted(self):
        """Strictness must not reject the shape the docs tell people to write."""
        self.write_rules(senders=["dana"], domains=["x.example"],
                         channels=["C01"])
        self.insert([self.item(source_id="keep", sender="Sam")])
        self.assertEqual(self.rows(), ["keep"])

    def test_no_rules_file_at_all_is_not_an_error(self):
        """Absent is the ordinary state of a fresh install and must stay free."""
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


class TestExclusionSurvivesTheRealNormalizers(StoreCase):
    """Through `graph_message_to_item` and `slack_message_to_item`, not around.

    The first version of these tests built the item dictionary by hand, which
    is a shape neither normalizer produces: both store a display name in
    `sender` and dropped the address and the raw user id entirely. So a domain
    rule matched nothing on real mail and a `U…` rule matched nothing on real
    Slack, while tests asserting on hand-built dictionaries stayed green. A
    test that cannot see that is not evidence.
    """

    def write_rules(self, **rules):
        (self.workspace / exclusions.RULES_FILE).write_text(
            json.dumps(rules), encoding="utf-8")

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return [r[0] for r in conn.execute("SELECT source_id FROM items")]

    def graph_message(self, name="Dana Okoro",
                      address="dana@agency.example", mid="g1"):
        """The shape Microsoft Graph actually returns: a name and an address."""
        return {
            "id": mid,
            "receivedDateTime": "2026-08-01T09:00:00Z",
            "subject": "about the cutover",
            "body": {"content": "text"},
            "from": {"emailAddress": {"name": name, "address": address}},
            "toRecipients": [{"emailAddress": {"address": "me@example.com"}}],
            "isRead": False,
        }

    def slack_message(self, uid="U01RECRUIT", display="friendly",
                      ts="1787000000.0001"):
        return ({"ts": ts, "user": uid, "text": "hello"},
                {"id": "D01", "type": "im"}, "U0ME", display)

    def insert(self, items):
        with sqlite3.connect(self.db) as conn:
            insert_items(conn, items)

    def test_a_domain_rule_matches_real_graph_mail(self):
        """`sender` holds the display name, so the address must survive too."""
        self.write_rules(domains=["agency.example"])
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com")])
        self.assertEqual(self.rows(), [])

    def test_an_address_rule_matches_real_graph_mail(self):
        self.write_rules(senders=["dana@agency.example"])
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com")])
        self.assertEqual(self.rows(), [])

    def test_the_display_name_still_matches(self):
        self.write_rules(senders=["Dana Okoro"])
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com")])
        self.assertEqual(self.rows(), [])

    def test_unrelated_graph_mail_still_arrives(self):
        """Otherwise the three above would pass on a store that writes nothing."""
        self.write_rules(domains=["agency.example"])
        self.insert([graph_message_to_item(
            self.graph_message(name="Sam Ruiz", address="sam@example.com",
                               mid="keep"), "me@example.com")])
        self.assertEqual(self.rows(), ["keep"])

    def test_a_slack_id_rule_matches_a_resolved_display_name(self):
        """The id is what a person cannot change; the display name is not."""
        self.write_rules(senders=["U01RECRUIT"])
        self.insert([slack_message_to_item(*self.slack_message())])
        self.assertEqual(self.rows(), [])

    def test_unrelated_slack_still_arrives(self):
        self.write_rules(senders=["U01RECRUIT"])
        msg, channel, me, display = self.slack_message(
            uid="U0SAM0001", display="sam", ts="1787000000.0002")
        self.insert([slack_message_to_item(msg, channel, me, display)])
        self.assertEqual(len(self.rows()), 1)

    def test_the_matching_values_are_never_stored(self):
        """Matching material must not become a new thing the store holds."""
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com"),
                     slack_message_to_item(*self.slack_message())])
        with sqlite3.connect(self.db) as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
            everything = "".join(
                str(v) for row in conn.execute("SELECT * FROM items")
                for v in row)
        self.assertNotIn("sender_address", columns)
        self.assertNotIn("sender_id", columns)
        self.assertNotIn("dana@agency.example", everything)
        self.assertNotIn("U01RECRUIT", everything)


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

    def test_the_export_is_no_more_readable_than_the_store(self):
        """The store is owner-only on purpose; a copy that is not undoes it."""
        self.add("m1")
        memory = self.workspace / "memory"
        memory.mkdir(exist_ok=True)
        (memory / "index.md").write_text("x", encoding="utf-8")
        destination = Path(self.home) / "out"
        export_store.export(destination)

        self.assertEqual(oct(destination.stat().st_mode)[-3:], "700")
        for name in ("store.json", "store.md"):
            self.assertEqual(
                oct((destination / name).stat().st_mode)[-3:], "600", name)
        for path in destination.rglob("*"):
            expected = "700" if path.is_dir() else "600"
            self.assertEqual(oct(path.stat().st_mode)[-3:], expected, str(path))

    def test_a_table_that_cannot_be_read_fails_the_export(self):
        """An empty section reads as "nothing was there", which is a lie.

        Dropping a table does not reproduce this: `export` calls
        `ensure_store` first and the baseline DDL puts it back, empty. What is
        being pinned is narrower and is the thing that regressed — that a read
        error is not converted into an empty table.
        """
        self.add("m1")
        original = export_store.rows

        def refuse(conn, table):
            if table == "events":
                raise sqlite3.OperationalError("disk I/O error")
            return original(conn, table)

        export_store.rows = refuse
        try:
            with self.assertRaises(sqlite3.Error):
                export_store.export(Path(self.home) / "out")
        finally:
            export_store.rows = original

    def test_a_failed_export_does_not_leave_a_complete_looking_one(self):
        """Half an export that reads as whole is the failure being avoided."""
        self.add("m1")
        original = export_store.rows

        def refuse(conn, table):
            if table == "events":
                raise sqlite3.OperationalError("disk I/O error")
            return original(conn, table)

        destination = Path(self.home) / "out"
        export_store.rows = refuse
        try:
            with self.assertRaises(sqlite3.Error):
                export_store.export(destination)
        finally:
            export_store.rows = original
        self.assertFalse((destination / "store.json").exists())
        self.assertFalse((destination / "store.md").exists())

    def test_a_long_body_is_marked_rather_than_silently_cut(self):
        """The readable form is bounded; it has to say so."""
        self.add("long", body="x" * (export_store.BODY_PREVIEW + 500))
        destination = Path(self.home) / "out"
        export_store.export(destination)
        text = (destination / "store.md").read_text(encoding="utf-8")
        self.assertIn("body continues", text)
        self.assertIn("store.json", text)

    def test_the_machine_form_holds_the_whole_body(self):
        """Bounded is the Markdown's property, not the export's."""
        whole = "x" * (export_store.BODY_PREVIEW + 500)
        self.add("long", body=whole)
        destination = Path(self.home) / "out"
        export_store.export(destination)
        data = json.loads(
            (destination / "store.json").read_text(encoding="utf-8"))
        stored = [i["body"] for i in data["items"] if i["source_id"] == "long"]
        self.assertEqual(stored, [whole])

    def test_a_short_body_is_not_marked(self):
        self.add("short", body="the cutover window is Thursday")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        text = (destination / "store.md").read_text(encoding="utf-8")
        self.assertIn("cutover window is Thursday", text)
        self.assertNotIn("body continues", text)

    def test_a_link_out_of_the_workspace_stops_the_export(self):
        """`copytree` follows links, so one under memory/ copies a file from
        anywhere on the machine into something about to be handed over."""
        self.add("m1")
        outside = Path(self.home) / "outside-the-workspace.txt"
        outside.write_text("private", encoding="utf-8")
        memory = self.workspace / "memory"
        memory.mkdir(exist_ok=True)
        (memory / "leak.md").symlink_to(outside)

        destination = Path(self.home) / "out"
        with self.assertRaises(export_store.ExportEscapesWorkspace):
            export_store.export(destination)
        self.assertFalse(destination.exists(),
                         "a refused export must leave nothing behind")

    def test_a_link_inside_the_workspace_is_fine(self):
        """The rule is about leaving the boundary, not about links."""
        self.add("m1")
        memory = self.workspace / "memory"
        memory.mkdir(exist_ok=True)
        (memory / "real.md").write_text("page", encoding="utf-8")
        (memory / "alias.md").symlink_to(memory / "real.md")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        self.assertTrue((destination / "memory" / "alias.md").exists())

    def test_an_export_is_a_snapshot_not_an_accumulation(self):
        """The default destination is date-based and reused all day, so a page
        deleted since the last export survived into the next one."""
        self.add("m1")
        memory = self.workspace / "memory"
        memory.mkdir(exist_ok=True)
        (memory / "gone.md").write_text("deleted later", encoding="utf-8")
        (memory / "kept.md").write_text("still here", encoding="utf-8")
        destination = Path(self.home) / "out"
        export_store.export(destination)
        self.assertTrue((destination / "memory" / "gone.md").exists())

        (memory / "gone.md").unlink()
        export_store.export(destination)
        self.assertFalse((destination / "memory" / "gone.md").exists(),
                         "a removed page survived the next export")
        self.assertTrue((destination / "memory" / "kept.md").exists())

    def test_a_stale_store_file_does_not_survive_either(self):
        self.add("m1")
        destination = Path(self.home) / "out"
        destination.mkdir()
        (destination / "store.md").write_text("yesterday", encoding="utf-8")
        (destination / "leftover.txt").write_text("stale", encoding="utf-8")
        export_store.export(destination)
        self.assertNotIn("yesterday",
                         (destination / "store.md").read_text(encoding="utf-8"))
        self.assertFalse((destination / "leftover.txt").exists())

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
        """Left behind, the next run re-reads windows the user just cleared.

        Asserted on the file rather than on a key name, because the key names
        are an implementation detail that changed once already while the
        guarantee did not.
        """
        self.populate()
        probed = self.workspace / "slack_capabilities.json"
        probed.write_text("{}", encoding="utf-8")
        reset.main(["--yes"])
        self.assertFalse(probed.exists())

    # Written out rather than read from `reset.COLLECTION_STATE`. Deriving the
    # fixture from the constant under test makes the test agree with whatever
    # the constant says: shrink it and the test creates fewer files and still
    # passes, which is how the original defect would have survived this very
    # test. These are the names a collector actually writes.
    WRITTEN_BY_COLLECTORS = (
        "slack_capabilities.json",
        "slack_channels.json",
        "slack_threads.json",
        "slack_rotation.json",
        "graph_identity.json",
        "exclusions.json",
    )

    def test_every_collection_state_file_goes(self):
        """The reproduced defect: four files survived a successful reset.

        `slack_capabilities.json` was listed and the rest were not, so a reset
        reported success while the channel list, the thread watermarks, the
        rotation offset and the exclusion rules stayed on disk — and the next
        scheduled tick re-read windows the user had just cleared.
        """
        self.populate()
        for name in self.WRITTEN_BY_COLLECTORS:
            (self.workspace / name).write_text("{}", encoding="utf-8")

        self.assertEqual(reset.main(["--yes"]), 0)

        left = sorted(p.name for p in self.workspace.glob("*")
                      if p.is_file())
        self.assertEqual(left, [], f"survived a successful reset: {left}")

    def test_the_listed_state_matches_what_collectors_write(self):
        """Both directions: nothing unlisted, and nothing listed that is gone."""
        self.assertEqual(sorted(reset.COLLECTION_STATE),
                         sorted(self.WRITTEN_BY_COLLECTORS))

    def test_a_workspace_file_nobody_listed_is_caught_here(self):
        """How the defect happened: a collector added state and this list did
        not. A glob would hide the next one; this fails instead."""
        self.populate()
        (self.workspace / "some_future_collector.json").write_text(
            "{}", encoding="utf-8")

        reset.main(["--yes"])

        left = sorted(p.name for p in self.workspace.glob("*") if p.is_file())
        self.assertEqual(
            left, ["some_future_collector.json"],
            "this test is the reminder: add the file to "
            "reset.COLLECTION_STATE, then add it here")

    def test_the_survey_names_them_before_they_go(self):
        """`--dry-run` is what somebody reads before consenting."""
        self.populate()
        for name in self.WRITTEN_BY_COLLECTORS:
            (self.workspace / name).write_text("{}", encoding="utf-8")
        surveyed = reset.survey()
        for name in self.WRITTEN_BY_COLLECTORS:
            self.assertEqual(surveyed.get(name), 1, name)

    def test_it_says_what_order_to_stop_things_in(self):
        """Detaching without pausing the schedule refills the store."""
        self.populate()
        script = ("import sys; sys.path.insert(0, %r)\n"
                  "import reset\nraise SystemExit(reset.main(['--yes']))"
                  % str(HERE))
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True,
                              env={**os.environ, "HERMES_HOME": self.home})
        self.assertIn("cron pause", proc.stderr)
        self.assertIn("provider detach", proc.stderr)
        self.assertIn("in order", proc.stderr)

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
