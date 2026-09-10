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
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import exclusions  # noqa: E402
import export_store  # noqa: E402
import reset  # noqa: E402
import retention  # noqa: E402
import skill_overrides  # noqa: E402
import skill_override_bundle  # noqa: E402
from normalize import (  # noqa: E402
    graph_message_to_item, insert_items, slack_message_to_item)

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")


def iso(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.distribution = Path(tempfile.mkdtemp())
        (self.distribution / "skills").mkdir()
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
        shutil.rmtree(self.distribution, ignore_errors=True)

    def register_shipped(self, name):
        source = self.distribution / "skills" / name / "SKILL.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((Path(self.home) / "skills" / name / "SKILL.md").read_bytes())
        skill_overrides.record_distribution(Path(self.home), self.distribution)

    def fork_shipped(self, name):
        self.register_shipped(name)
        return skill_overrides.fork_skill(Path(self.home), name)

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

    def test_an_excluded_senders_values_never_reach_the_store(self):
        """The guarantee that survived the identity column.

        The store now keeps one stable identity per sender, so an address is
        no longer absent from every row — see `sender_key` in `schema.sql`.
        What is still absolute is the exclusion boundary: matching happens
        inside `insert_items`, before the write, so a sender the user excluded
        contributes nothing at all, identity included.
        """
        self.write_rules(senders=["dana@agency.example", "U01RECRUIT"])
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com"),
                     slack_message_to_item(*self.slack_message())])
        with sqlite3.connect(self.db) as conn:
            everything = "".join(
                str(v) for row in conn.execute("SELECT * FROM items")
                for v in row)
        self.assertEqual(self.rows(), [])
        self.assertNotIn("dana@agency.example", everything)
        self.assertNotIn("U01RECRUIT", everything)

    def test_the_matching_fields_are_still_not_columns_of_their_own(self):
        """One identity column, not a growing set of per-source ones.

        `sender_address` and `sender_id` remain what they were — values the
        normalizers compute for matching and drop. The identity that is kept
        is a single column both sources agree on, so a rule, a page and a row
        all mean the same thing by a sender.
        """
        self.insert([graph_message_to_item(self.graph_message(),
                                           "me@example.com"),
                     slack_message_to_item(*self.slack_message())])
        with sqlite3.connect(self.db) as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
            keys = [r[0] for r in conn.execute(
                "SELECT sender_key FROM items ORDER BY source_id")]
        self.assertNotIn("sender_address", columns)
        self.assertNotIn("sender_id", columns)
        self.assertEqual(keys, ["U01RECRUIT", "dana@agency.example"])


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

    def live_workspace(self):
        """Everything a refusal has to leave untouched."""
        self.add("m1")
        memory = self.workspace / "memory"
        memory.mkdir(exist_ok=True)
        (memory / "index.md").write_text("the memory", encoding="utf-8")
        policy = self.workspace / "policy"
        policy.mkdir(exist_ok=True)
        (policy / "preferences.md").write_text("the policy", encoding="utf-8")

    def assert_workspace_intact(self):
        self.assertTrue(self.db.exists(), "the live store was removed")
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute("SELECT count(*) FROM items").fetchone()[0]
        self.assertEqual(rows, 1, "the live store lost rows")
        self.assertEqual(
            (self.workspace / "memory" / "index.md").read_text(
                encoding="utf-8"), "the memory")
        self.assertEqual(
            (self.workspace / "policy" / "preferences.md").read_text(
                encoding="utf-8"), "the policy")

    def test_exporting_into_the_workspace_is_refused(self):
        """The export replaces its destination, so this deleted the store and
        left a copy of it in place — reported as success."""
        self.live_workspace()
        with self.assertRaises(export_store.ExportOverlapsWorkspace):
            export_store.export(self.workspace)
        self.assert_workspace_intact()

    def test_exporting_inside_the_workspace_is_refused(self):
        self.live_workspace()
        with self.assertRaises(export_store.ExportOverlapsWorkspace):
            export_store.export(self.workspace / "memory")
        self.assert_workspace_intact()

    def test_exporting_into_a_directory_containing_the_workspace_is_refused(self):
        self.live_workspace()
        with self.assertRaises(export_store.ExportOverlapsWorkspace):
            export_store.export(Path(self.home))
        self.assert_workspace_intact()

    def test_the_refusal_leaves_no_staging_directory(self):
        """Refused before anything is created, so nothing is left to clean."""
        self.live_workspace()
        before = sorted(p.name for p in Path(self.home).iterdir())
        with self.assertRaises(export_store.ExportOverlapsWorkspace):
            export_store.export(self.workspace)
        self.assertEqual(sorted(p.name for p in Path(self.home).iterdir()),
                         before)

    def test_a_destination_beside_the_workspace_is_fine(self):
        """The rule is about overlap, not about being nearby."""
        self.live_workspace()
        destination = Path(self.home) / "export-out"
        export_store.export(destination)
        self.assertTrue((destination / "store.json").exists())
        self.assert_workspace_intact()

    def test_the_command_reports_the_refusal_rather_than_raising(self):
        self.live_workspace()
        self.assertEqual(
            export_store.main(["--to", str(self.workspace)]), 1)
        self.assert_workspace_intact()

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

    def test_a_skill_overrides_own_text_travels_with_it(self):
        """Not the retained history or the bookkeeping database, but the
        one thing the user actually wrote — losing it in an export-then-
        reset cycle would be exactly the failure this command exists to
        avoid."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.assertEqual(
            self.fork_shipped("inbound-judging").kind,
            "forked")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nEdited.\n"
        override_path.write_text(override_text, encoding="utf-8")

        destination = Path(self.home) / "out"
        report = export_store.export(destination)

        self.assertEqual(report["skill_overrides"], 1)
        exported = (destination / "skill-overrides" / "overrides"
                   / "inbound-judging" / "SKILL.md")
        self.assertEqual(exported.read_text(encoding="utf-8"), override_text)

    def _export_applied_override(self):
        name = "inbound-judging"
        live = Path(self.home) / "skills" / name / "SKILL.md"
        live.parent.mkdir(parents=True)
        shipped = "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n"
        live.write_text(shipped, encoding="utf-8")
        self.fork_shipped(name)
        override = self.workspace / "skill-overrides" / "overrides" / name / "SKILL.md"
        edited = override.read_text(encoding="utf-8") + "\nEdited.\n"
        override.write_text(edited, encoding="utf-8")
        skill_overrides.apply_overrides(Path(self.home))
        destination = Path(self.home) / "out"
        export_store.export(destination)
        return live, shipped, edited, destination / "skill-overrides-recovery.json"

    def test_export_reset_restore_preserves_the_base_manifest_and_history(self):
        live, shipped, edited, bundle = self._export_applied_override()
        before = json.loads(bundle.read_text())["tables"]
        self.assertEqual(reset.main(["--yes"]), 0)
        self.assertEqual(live.read_text(), shipped)
        skill_override_bundle.restore_bundle(Path(self.home), bundle)
        self.assertEqual(live.read_text(), shipped, "restore does not write live skills")
        with sqlite3.connect(self.workspace / "skill-overrides" / "state.db") as conn:
            conn.row_factory = sqlite3.Row
            for table, rows in before.items():
                self.assertEqual([dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")], rows)
        self.assertEqual([r.kind for r in skill_overrides.apply_overrides(Path(self.home))], ["applied"])
        self.assertEqual(live.read_text(), edited)
        self.assertEqual(skill_overrides.remove_override(Path(self.home), "inbound-judging").kind, "removed")
        self.assertEqual(live.read_text(), shipped)

    def test_restoring_against_a_newer_install_keeps_the_override_blocked(self):
        live, shipped, edited, bundle = self._export_applied_override()
        self.assertEqual(reset.main(["--yes"]), 0)
        newer = shipped.replace("description: shipped", "description: newer")
        live.write_text(newer, encoding="utf-8")
        skill_override_bundle.restore_bundle(Path(self.home), bundle)
        self.assertEqual([r.kind for r in skill_overrides.apply_overrides(Path(self.home))], ["blocked"])
        self.assertEqual(live.read_text(), newer)
        self.register_shipped("inbound-judging")
        self.assertEqual([r.kind for r in skill_overrides.apply_overrides(Path(self.home))], ["skipped-stale"])
        self.assertEqual(live.read_text(), newer)
        # The old relationship remains recoverable; removal uses the newly
        # accepted version, without having to manufacture a fresh fork.
        self.assertEqual(skill_overrides.remove_override(Path(self.home), "inbound-judging").kind, "removed")
        self.assertEqual(live.read_text(), newer)

    def test_an_invalid_utf8_override_is_preserved_byte_for_byte(self):
        """Losing the user's own bytes because they are hard to validate
        would be the same silent omission a valid override losing its
        text would be — the override is still reported (as an error, its
        own content being unreadable as text), but exported whole."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        malformed = override_path.read_bytes() + b"\nBroken: \xff\xfe not utf-8\n"
        override_path.write_bytes(malformed)

        destination = Path(self.home) / "out"
        report = export_store.export(destination)

        self.assertEqual(report["skill_overrides"], 1)
        exported = (destination / "skill-overrides" / "overrides"
                   / "inbound-judging" / "SKILL.md")
        self.assertEqual(exported.read_bytes(), malformed,
                         "an override that fails to validate must still be "
                         "exported byte-for-byte, not silently omitted")

    def test_an_unreadable_override_aborts_the_export_rather_than_omitting_it(self):
        """The regression this reproduces: a `read_bytes()` failure on an
        override file that genuinely exists — permission denied, not
        absence — used to be caught into an 'error' Report with
        `text=None`, which `export_store.py` then silently skipped
        writing while still finishing the export and reporting success.
        That contradicts the documented 'nothing is omitted' contract as
        surely as a symlink under `memory/` would."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")

        real_read_bytes = Path.read_bytes

        def refuse(self):
            if self == override_path:
                raise PermissionError(13, "Permission denied")
            return real_read_bytes(self)

        Path.read_bytes = refuse
        destination = Path(self.home) / "out"
        try:
            with self.assertRaises(PermissionError):
                export_store.export(destination)
        finally:
            Path.read_bytes = real_read_bytes

        self.assertFalse(
            destination.exists(),
            "a capture failure must leave no export directory at all, "
            "not one silently missing the override it could not read")
        self.assertEqual(
            list(destination.parent.glob(".export-*")), [],
            "a failed export must leave no leaked staging directory "
            "behind either — checking only the destination's own "
            "absence would pass even if `export()`'s own cleanup left "
            "a sibling `.export-*` directory behind")

    def test_a_symlinked_orphaned_override_directory_aborts_the_export(self):
        """The regression this reproduces: the strict enumerator used to
        silently filter out a symlinked child directory under
        overrides/ instead of raising, so an orphaned override sitting
        behind one was never even attempted — not captured, not even
        reported as an error — while export still finished and reported
        success."""
        overrides_dir = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides")
        overrides_dir.mkdir(parents=True)
        real_target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, real_target, ignore_errors=True)
        (real_target / "SKILL.md").write_text(
            "---\nname: orphaned-skill\ndescription: x\nbased_on_sha256: "
            + "0" * 64 + "\n---\n\nbody\n", encoding="utf-8")
        (overrides_dir / "orphaned-skill").symlink_to(real_target)

        destination = Path(self.home) / "out"
        with self.assertRaises(skill_overrides.UnsafePath):
            export_store.export(destination)
        self.assertFalse(
            destination.exists(),
            "an unsafe entry in the candidate listing must leave no "
            "export directory at all, not one silently missing the "
            "orphaned override behind it")
        self.assertEqual(
            list(destination.parent.glob(".export-*")), [],
            "a failed export must leave no leaked staging directory "
            "behind either — checking only the destination's own "
            "absence would pass even if `export()`'s own cleanup left "
            "a sibling `.export-*` directory behind")

    def test_a_regular_file_where_memory_should_be_a_directory_aborts_the_export(self):
        """The regression this reproduces: a regular file (or FIFO, or
        anything else non-directory) sitting at `workspace/memory`
        looked exactly like absence to the old `Path.is_dir()` check —
        silently skipped, not reported. Worse than most omissions:
        `reset.py` still deletes whatever is at that exact path as one
        of its own targets, so an export-then-reset cycle could lose it
        without export ever having captured it first."""
        memory_path = Path(self.home) / "workspace" / "memory"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text("not a directory\n", encoding="utf-8")

        destination = Path(self.home) / "out"
        with self.assertRaises(export_store.ExportEscapesWorkspace):
            export_store.export(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.glob(".export-*")), [])

    def test_a_publication_failure_cleans_up_the_staging_export(self):
        """The regression this reproduces: publication (removing
        whatever was at the destination, then the final rename) used to
        sit outside the try/except that cleans up the staging directory
        — so any failure at that specific point, after the fully-built
        export already exists in staging, left it behind as a leaked
        `.export-*` sibling even though the command as a whole failed.
        `os.replace` itself is what is made to fail here, deliberately
        independent of any earlier destination-inspection fix, to prove
        the cleanup boundary now covers publication generally, not just
        the specific failure that first exposed the gap."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("inbound-judging")

        destination = Path(self.home) / "out"
        real_replace = export_store.os.replace

        def refuse(src, dst):
            raise OSError(18, "Invalid cross-device link")

        export_store.os.replace = refuse
        try:
            with self.assertRaises(OSError):
                export_store.export(destination)
        finally:
            export_store.os.replace = real_replace

        self.assertFalse(destination.exists())
        self.assertEqual(
            list(destination.parent.glob(".export-*")), [],
            "the fully-built staging export must not survive a "
            "publication failure as a leaked sibling directory")


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
        "slack_thread_rotation.json",
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

        # `.skill-overrides-global.lock` is the one deliberate, documented
        # exception (see the comment beside `reset.targets()`): it is the
        # barrier `remove()` itself holds exclusively while deleting
        # everything else, so deleting it from inside that same hold
        # would recreate the inode-swap race the lock exists to close.
        left = sorted(p.name for p in self.workspace.glob("*")
                      if p.is_file() and p.name != ".skill-overrides-global.lock")
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

        left = sorted(p.name for p in self.workspace.glob("*")
                      if p.is_file() and p.name != ".skill-overrides-global.lock")
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

    def test_a_dangling_target_symlink_is_removed_not_reported_absent(self):
        """The regression this reproduces: `os.stat()` follows a
        symlink, so a target replaced by one whose destination does not
        exist made the old strict check's own `FileNotFoundError` (from
        looking up the missing destination, not the symlink itself) read
        as "nothing here" — the dangling symlink itself was never
        recorded as present, and never removed, while reset still
        reported success."""
        self.populate()
        target = reset.targets()["exclusions.json"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(target.parent / "does-not-exist")
        self.assertTrue(target.is_symlink())

        self.assertEqual(reset.main(["--yes"]), 0)
        self.assertFalse(
            target.is_symlink(),
            "a dangling target symlink must actually be removed, not "
            "silently left in place because its destination is missing")

    def test_a_populated_skill_overrides_directory_is_removed(self):
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        (skill_dir / "SKILL.md").write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nCustomized.\n"
        override_path.write_text(override_text, encoding="utf-8")
        skill_overrides.apply_overrides(Path(self.home))
        live_path = skill_dir / "SKILL.md"
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text,
                         "the override should be live before reset runs")
        state_dir = Path(self.home) / "workspace" / "skill-overrides"
        self.assertTrue(state_dir.exists())

        self.assertEqual(reset.main(["--yes"]), 0)

        self.assertFalse(state_dir.exists())
        self.assertEqual(
            live_path.read_text(encoding="utf-8"), shipped_text,
            "reset must restore the live skill to shipped content, not just "
            "delete the bookkeeping that tracked the customization")

    def test_reset_preserves_an_unregistered_update_and_removes_tracked_data(self):
        """A bare profile update can replace an applied override before its
        source is registered. The new live bytes are not this feature's write,
        so reset must preserve them without making source registration a
        prerequisite for deleting the user's tracked recipe data."""
        self.populate()
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        live_path = skill_dir / "SKILL.md"
        live_path.write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (self.workspace / "skill-overrides" / "overrides"
                         / "inbound-judging" / "SKILL.md")
        override_path.write_text(
            override_path.read_text(encoding="utf-8") + "\nCustomized.\n",
            encoding="utf-8")
        skill_overrides.apply_overrides(Path(self.home))

        updated_text = ("---\nname: inbound-judging\n"
                        "description: unregistered profile update\n---\n\n"
                        "new shipped body\n")
        live_path.write_text(updated_text, encoding="utf-8")

        self.assertEqual(reset.main(["--yes"]), 0)
        self.assertEqual(live_path.read_text(encoding="utf-8"), updated_text)
        self.assertFalse(self.db.exists())
        self.assertFalse((self.workspace / "skill-overrides").exists())

    def test_reset_still_restores_a_hand_deleted_override_after_a_scheduled_apply_tick(self):
        """The regression this reproduces: a stale applied_overrides row
        used to be cleared unconditionally the moment the override file
        went missing, even though live content hadn't actually changed —
        discarding the one thing reset's own restoration candidate list
        depends on to find this skill at all, one apply tick before reset
        ever got a chance to look."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        (skill_dir / "SKILL.md").write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nCustomized.\n"
        override_path.write_text(override_text, encoding="utf-8")
        skill_overrides.apply_overrides(Path(self.home))
        live_path = skill_dir / "SKILL.md"

        # Deleted by hand, not through --remove — live content is still
        # exactly the override.
        override_path.unlink()
        # One ordinary scheduled apply tick runs before reset does.
        skill_overrides.apply_overrides(Path(self.home))
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text,
                         "the apply tick must not have touched live content")

        self.assertEqual(reset.main(["--yes"]), 0)

        self.assertEqual(
            live_path.read_text(encoding="utf-8"), shipped_text,
            "reset must still restore this skill even after an apply tick "
            "ran with the override file already gone")

    def test_reset_does_not_canonize_a_crashed_apply_as_shipped_content(self):
        """The regression this reproduces: a crash between apply's file
        write and its completion commit left an override live with no
        applied_overrides row yet — and without recognizing the still-
        pending operation as this feature's own, reset's own observation
        step read that live content as a fresh shipped version and wrote
        it right back, permanently canonizing an override that was never
        actually confirmed applied."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        live_path = skill_dir / "SKILL.md"
        live_path.write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nCustomized.\n"
        override_path.write_text(override_text, encoding="utf-8")

        # The exact state a crash between apply's file write and its
        # completion commit leaves: live already holds the override, a
        # pending journal row expects exactly this write's result, but no
        # applied_overrides row exists yet.
        before_hash = skill_overrides._sha256(shipped_text)
        after_hash = skill_overrides._sha256(override_text)
        live_path.write_text(override_text, encoding="utf-8")
        db_path = (Path(self.home) / "workspace" / "skill-overrides" / "state.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'apply', 'pending', ?, ?)",
                (before_hash, after_hash))

        self.assertEqual(reset.main(["--yes"]), 0)

        self.assertEqual(
            live_path.read_text(encoding="utf-8"), shipped_text,
            "reset must restore the shipped version, not canonize the "
            "unconfirmed crashed override as if it were shipped content")

    def test_reset_finds_the_pending_only_crash_state_even_when_skills_cannot_be_listed(self):
        """The regression this specifically proves, that the test above
        does not: `_list_pending_operation_skill_names()` was added
        because the pending-only crash state (override file gone, no
        applied row, only a pending operation row to show for it) must
        be found independently of whether `skills/` can even be
        enumerated — `iterdir()` and a direct `stat()` on a known path
        are allowed to disagree about what is readable. The test above
        leaves the override file in place, so the skill is trivially
        discoverable through the ordinary override listing regardless of
        whether the new source works at all. This one removes every
        other way of finding it and monkeypatches `_list_skill_names`
        itself to return nothing, so the only thing that can find this
        skill is the new database-backed source."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        live_path = skill_dir / "SKILL.md"
        live_path.write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nCustomized.\n"

        before_hash = skill_overrides._sha256(shipped_text)
        after_hash = skill_overrides._sha256(override_text)
        live_path.write_text(override_text, encoding="utf-8")
        db_path = (Path(self.home) / "workspace" / "skill-overrides" / "state.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'apply', 'pending', ?, ?)",
                (before_hash, after_hash))
        # Hand-deleted on top of the crash state above, so neither the
        # override listing nor an applied row can find this skill either
        # — only the pending-operation row can. The empty parent
        # directory left behind by unlinking just the file is removed
        # too: `_list_overridden_skill_names()` enumerates directory
        # names under `overrides/`, not whether `SKILL.md` exists inside
        # one, so leaving it in place would let that listing keep
        # finding this skill regardless of whether the new
        # pending-operations source works at all.
        override_path.unlink()
        override_path.parent.rmdir()

        root = Path(self.home)
        self.assertNotIn(
            "inbound-judging", skill_overrides._list_overridden_skill_names(root),
            "the override listing must not be able to find this skill "
            "either, or this test does not actually isolate the new "
            "pending-operations source")
        self.assertNotIn(
            "inbound-judging", skill_overrides._list_applied_skill_names(root),
            "no applied row exists in this crash state, so the applied "
            "listing must not find this skill either")

        real_list_skill_names = skill_overrides._list_skill_names
        skill_overrides._list_skill_names = lambda root: []
        try:
            self.assertEqual(reset.main(["--yes"]), 0)
        finally:
            skill_overrides._list_skill_names = real_list_skill_names

        self.assertEqual(
            live_path.read_text(encoding="utf-8"), shipped_text,
            "reset must still find and restore this skill via the "
            "pending-operation database listing alone, even when the "
            "ordinary shipped-skill listing finds nothing at all")

    def test_reset_refuses_a_skill_with_diverged_pending_state_rather_than_guessing(self):
        """The regression this reproduces: a pending apply A->O, with
        the override file gone and live content changed to X (matching
        neither A nor O — something outside this module's cooperating
        writers touched it), used to either report the skill restored
        while silently deleting the one journal row that explained the
        divergence, or record X itself as a trusted new shipped base
        before overwriting it. Reset must refuse this skill outright,
        deleting nothing anywhere, rather than guess which of those two
        wrong answers to give."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        shipped_text = ("---\nname: inbound-judging\ndescription: shipped\n"
                        "---\n\nbody\n")
        live_path = skill_dir / "SKILL.md"
        live_path.write_text(shipped_text, encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_path = (Path(self.home) / "workspace" / "skill-overrides"
                         / "overrides" / "inbound-judging" / "SKILL.md")
        override_text = override_path.read_text(encoding="utf-8") + "\nO.\n"

        before_hash = skill_overrides._sha256(shipped_text)
        after_hash = skill_overrides._sha256(override_text)
        db_path = (Path(self.home) / "workspace" / "skill-overrides" / "state.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'apply', 'pending', ?, ?)",
                (before_hash, after_hash))
        # Diverged: neither the pre-apply shipped text (A) nor the
        # override's own content (O) — something else entirely.
        diverged_text = "something else entirely\n"
        live_path.write_text(diverged_text, encoding="utf-8")
        override_path.unlink()

        ops_before = self._all_rows(db_path, "override_operations")

        self.assertEqual(reset.main(["--yes"]), 1)

        self.assertEqual(
            live_path.read_text(encoding="utf-8"), diverged_text,
            "a diverged skill's live content must be left exactly as "
            "found, not overwritten with a guess")
        self.assertTrue(
            (Path(self.home) / "workspace" / "skill-overrides").exists(),
            "nothing may be deleted while any skill's state is genuinely "
            "unresolved")
        self.assertEqual(
            self._all_rows(db_path, "override_operations"), ops_before,
            "the pending row that explains the divergence must survive "
            "a refused reset untouched")

    def _all_rows(self, db_path: Path, table: str) -> list[tuple]:
        with sqlite3.connect(db_path) as conn:
            return conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()

    def test_one_skill_failing_to_restore_leaves_a_successful_skills_override_untouched(self):
        """The regression this reproduces: restoring skill A used to
        delete A's override file and bookkeeping as soon as A itself
        succeeded — so when a later skill B then failed, reset reported
        'nothing has been removed' while A's customization was, in fact,
        already gone. Restoring must not mutate any skill's override or
        bookkeeping at all until every skill in the batch has succeeded."""
        skill_a_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_a_dir.mkdir(parents=True)
        (skill_a_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("inbound-judging")
        override_a = (Path(self.home) / "workspace" / "skill-overrides"
                      / "overrides" / "inbound-judging" / "SKILL.md")
        override_a_text = override_a.read_text(encoding="utf-8") + "\nA.\n"
        override_a.write_text(override_a_text, encoding="utf-8")

        skill_b_dir = Path(self.home) / "skills" / "memory-writing"
        skill_b_dir.mkdir(parents=True)
        (skill_b_dir / "SKILL.md").write_text(
            "---\nname: memory-writing\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("memory-writing")
        override_b = (Path(self.home) / "workspace" / "skill-overrides"
                      / "overrides" / "memory-writing" / "SKILL.md")
        override_b_text = override_b.read_text(encoding="utf-8") + "\nB.\n"
        override_b.write_text(override_b_text, encoding="utf-8")

        # Both actually applied, not just forked: the point of this test
        # is that a failed reset leaves A's *bookkeeping* — its applied
        # row and operation journal, not merely its override file —
        # untouched, and there is nothing to protect there unless
        # something has actually been applied.
        skill_overrides.apply_overrides(Path(self.home))

        db_path = Path(self.home) / "workspace" / "skill-overrides" / "state.db"
        with sqlite3.connect(db_path) as conn:
            b_hash = conn.execute(
                "SELECT content_hash FROM base_observations"
                " WHERE skill_name='memory-writing'"
                " ORDER BY observation_id DESC LIMIT 1").fetchone()[0]
            a_applied_before = conn.execute(
                "SELECT * FROM applied_overrides"
                " WHERE skill_name='inbound-judging'").fetchone()
            a_ops_before = conn.execute(
                "SELECT * FROM override_operations"
                " WHERE skill_name='inbound-judging'"
                " ORDER BY id").fetchall()
        self.assertIsNotNone(
            a_applied_before,
            "A must actually be applied before the failed reset, or this "
            "test proves nothing about bookkeeping surviving one")
        self.assertTrue(a_ops_before)

        # Only B's own retained base becomes unusable — A's must remain
        # intact, so A's restoration would genuinely succeed in isolation.
        import shutil
        shutil.rmtree(Path(self.home) / "workspace" / "skill-overrides"
                      / "bases" / b_hash)

        self.assertEqual(reset.main(["--yes"]), 1)

        self.assertTrue(override_a.exists(),
                        "skill A's override must survive a batch reset "
                        "that failed on a different skill")
        self.assertEqual(override_a.read_text(encoding="utf-8"), override_a_text)
        self.assertTrue(override_b.exists())
        self.assertTrue(
            (Path(self.home) / "workspace" / "skill-overrides").exists(),
            "the whole bookkeeping tree must survive too — nothing is "
            "deleted until every skill restores successfully")

        with sqlite3.connect(db_path) as conn:
            a_applied_after = conn.execute(
                "SELECT * FROM applied_overrides"
                " WHERE skill_name='inbound-judging'").fetchone()
            a_ops_after = conn.execute(
                "SELECT * FROM override_operations"
                " WHERE skill_name='inbound-judging'"
                " ORDER BY id").fetchall()
        self.assertEqual(
            a_applied_after, a_applied_before,
            "every column of A's applied-overrides row (not just "
            "applied_hash) must be byte-for-byte unchanged by a batch "
            "reset that failed on B, not merely still present")
        self.assertEqual(
            a_ops_after, a_ops_before,
            "A's operation journal must be untouched too — restoration "
            "must not claim or journal anything on A's behalf just "
            "because it happened to succeed before B failed")

    def test_a_reset_refuses_while_a_skills_lock_is_held(self):
        """Reset deletes the very lock files that provide mutual
        exclusion — a raw rmtree while one is held could unlink it out
        from under a live operation. Refusing outright, rather than
        racing it, is the whole point of the check."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        self.fork_shipped("inbound-judging")

        import fcntl
        lock_path = (Path(self.home) / "workspace" / "skill-overrides"
                    / "locks" / "inbound-judging.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(reset.main(["--yes"]), 1)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        # Nothing was removed — the refusal must be all-or-nothing, not a
        # partial reset that skips only the locked skill.
        self.assertTrue((Path(self.home) / "workspace" / "skill-overrides").exists())
        self.assertTrue(self.db.exists())

        # And now that the lock is free, reset proceeds normally.
        self.assertEqual(reset.main(["--yes"]), 0)

    def test_reset_actually_blocks_a_new_skill_operation_not_just_the_precheck(self):
        """The real guarantee, proven with a real thread: `refuse_if_busy`
        is a fast early check that can miss an operation starting after
        it runs — the exclusive lock reset actually holds around deletion
        is what a new operation cannot get past regardless of timing."""
        skill_dir = Path(self.home) / "skills" / "inbound-judging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: shipped\n---\n\nbody\n",
            encoding="utf-8")
        # A real directory to rmtree, and released back so reset's own
        # restoration step has nothing left to do.
        self.fork_shipped("inbound-judging")
        skill_overrides.remove_override(Path(self.home), "inbound-judging")

        entered = threading.Event()
        proceed = threading.Event()
        real_rmtree = shutil.rmtree

        def slow_rmtree(path, *a, **kw):
            if Path(path).name == "skill-overrides":
                entered.set()
                proceed.wait(timeout=5)
            return real_rmtree(path, *a, **kw)

        reset.shutil.rmtree = slow_rmtree
        results = {}

        def do_reset():
            results["reset"] = reset.main(["--yes"])

        resetter = threading.Thread(target=do_reset)
        resetter.start()
        self.assertTrue(entered.wait(timeout=5),
                        "reset never reached its deletion step")

        # A new fork attempt must not be able to acquire this skill's
        # lock while reset holds the exclusive global lock.
        forked_while_blocked = threading.Event()

        def do_fork():
            self.fork_shipped("inbound-judging")
            forked_while_blocked.set()

        # By this point reset is parked inside `slow_rmtree`'s
        # `proceed.wait()`, holding the exclusive global lock but not
        # calling `flock` again — so the only thread that can reach this
        # wrapper before the negative assertion below is the forker.
        # Instrumenting the real `flock` call itself, rather than setting
        # a `threading.Event` merely before entering `fork_skill`, is
        # what makes this prove the forker actually reached the blocking
        # primitive rather than merely having been scheduled to run.
        import fcntl
        forker_attempting = threading.Event()
        real_flock = fcntl.flock

        def instrumented_flock(fd, operation):
            forker_attempting.set()
            return real_flock(fd, operation)

        fcntl.flock = instrumented_flock
        try:
            forker = threading.Thread(target=do_fork)
            forker.start()
            self.assertTrue(forker_attempting.wait(timeout=5),
                            "forker thread never reached its flock() call")
            self.assertFalse(forked_while_blocked.wait(timeout=0.3),
                             "a new skill operation proceeded while reset "
                             "held the exclusive lock")
        finally:
            fcntl.flock = real_flock

        proceed.set()
        resetter.join(timeout=5)
        forker.join(timeout=5)
        reset.shutil.rmtree = real_rmtree
        self.assertFalse(resetter.is_alive())
        self.assertFalse(forker.is_alive())
        self.assertEqual(results["reset"], 0)

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
