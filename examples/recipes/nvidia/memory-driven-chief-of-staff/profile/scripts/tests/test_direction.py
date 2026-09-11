# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""C1 keeps historical rows usable without treating outbound rows as asks."""

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import _db
import apply_decisions
import export_store
import migrate
import normalize
import outbound
import retention
import select_intake
import select_memory


class TestDirection(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        (self.home / "distribution.yaml").write_text("id: test\n")
        env = patch.dict(os.environ, {"HERMES_HOME": str(self.home), "INTAKE_GRAPH_SENT_ITEMS": "0",
                                       "INTAKE_SLACK_SELF_AUTHORED": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.db = _db.ensure_store()

    def add(self, sid, direction=None, body="inbound evidence"):
        with _db.write_txn() as conn:
            conn.execute(
                "INSERT INTO items(source_id, source, scope, event_at, sender,"
                " sender_key, body, addressing, direction) VALUES"
                " (?,'email','inbox',?,'Dana','dana@example.com',?,'direct',?)",
                (sid, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 body, direction))

    def intake(self):
        output = io.StringIO()
        with patch.object(select_intake, "collect", return_value=({}, False)), \
                contextlib.redirect_stdout(output):
            select_intake.main()
        text = output.getvalue()
        return json.loads(text.split('{"wakeAgent"')[0]), text

    def test_intake_keeps_unknown_and_inbound_rows(self):
        self.add("legacy")
        self.add("received", "inbound")
        self.add("sent", "outbound")
        payload, _ = self.intake()
        self.assertEqual({r["source_id"] for r in payload["slice"]},
                         {"legacy", "received"})

    def test_only_outbound_rows_do_not_wake_the_intake_agent(self):
        self.add("sent", "outbound")
        payload, output = self.intake()
        self.assertEqual(payload["slice"], [])
        self.assertEqual(json.loads(output.splitlines()[-1]), {"wakeAgent": False})

    def test_outbound_decisions_roll_back_the_whole_envelope(self):
        self.add("legacy")
        self.add("sent", "outbound")
        for verdict in ("CREATE", "KEEP_OPEN", "MARK_DONE", "SKIP"):
            with self.subTest(verdict=verdict):
                with self.assertRaisesRegex(ValueError, "outbound"):
                    apply_decisions.apply({"version": 1, "decisions": [
                        {"source_id": "legacy", "decision": "CREATE", "rank": 1,
                         "intent_gated": True, "title": "Review the proposal"},
                        {"source_id": "sent", "decision": verdict, "rank": 2,
                         "intent_gated": True, "title": "User-authored text"},
                    ], "cursor": {"source": "email", "scope": "inbox", "value": "next"}})
                with contextlib.closing(sqlite3.connect(self.db)) as conn:
                    for table in ("obligations", "events", "cursors"):
                        self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}")
                                         .fetchone()[0], 0)
                    self.assertEqual(conn.execute("SELECT DISTINCT state FROM items")
                                     .fetchall(), [("pending",)])

    def test_outbound_rows_cannot_create_a_person_candidate(self):
        for n in range(4):
            self.add(str(n), "outbound", "user-authored text")
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            payload = select_memory.evidence(conn, "2026-01-01T00:00:00Z")
        self.assertEqual(payload["people"], [])
        self.assertEqual(payload["interactions"], {})

    def test_people_keep_historical_evidence_without_outbound_text(self):
        for n in range(3):
            self.add(str(n))
        self.add("sent", "outbound", "user-authored text")
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            payload = select_memory.evidence(conn, "2026-01-01T00:00:00Z")
        self.assertEqual(len(payload["people"]), 1)
        self.assertIn("inbound evidence", json.dumps(payload))
        self.assertNotIn("user-authored text", json.dumps(payload))

    def test_insert_preserves_explicit_direction_and_pending_deadline(self):
        with _db.write_txn() as conn:
            normalize.insert_items(conn, [{
                "source_id": "sent", "source": "slack", "scope": "CEXAMPLE",
                "event_at": "2026-09-01T00:00:00Z", "direction": "outbound",
                "counterparty_pending_until": "2026-09-08T00:00:00Z",
            }])
            self.assertEqual(conn.execute(
                "SELECT direction, counterparty_pending_until FROM items").fetchone(),
                ("outbound", "2026-09-08T00:00:00Z"))

    def test_export_preserves_new_columns_and_unknown_values(self):
        self.add("legacy")
        self.add("sent", "outbound")
        with _db.write_txn() as conn:
            conn.execute("UPDATE items SET counterparty_pending_until=? WHERE source_id='sent'",
                         ("2026-09-08T00:00:00Z",))
        destination = self.home / "export"
        export_store.export(destination)
        exported = json.loads((destination / "store.json").read_text())
        rows = {r["source_id"]: r for r in exported["items"]}
        self.assertIsNone(rows["legacy"]["direction"])
        self.assertEqual(rows["sent"]["direction"], "outbound")
        self.assertEqual(rows["sent"]["counterparty_pending_until"],
                         "2026-09-08T00:00:00Z")

    def test_retention_clears_outbound_body_and_preserves_direction(self):
        self.add("sent", "outbound", "old text")
        with _db.write_txn() as conn:
            conn.execute("UPDATE items SET event_at='2000-01-01T00:00:00Z'")
        with contextlib.redirect_stdout(io.StringIO()):
            retention.main([])
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT body, direction, body_cleared_at FROM items").fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], "outbound")
        self.assertIsNotNone(row[2])

    def test_fresh_store_has_direction_indexes_and_rejects_invalid_direction(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            indexes = {r[1] for r in conn.execute("PRAGMA index_list(items)")}
            self.assertTrue({"idx_items_pending", "idx_items_counterparty_pending"} <= indexes)
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("bad", "sideways")

    def test_failed_v6_upgrade_rolls_back_columns_and_version(self):
        # Use the installation entry point, which owns the migration transaction.
        self.db.unlink()
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.executescript((HERE / "schema-v5.sql").read_text())
        upgrade = migrate.MIGRATIONS[6]

        def interrupted(conn):
            upgrade(conn)
            raise RuntimeError("interrupted migration")

        with patch.dict(migrate.MIGRATIONS, {6: interrupted}):
            with self.assertRaisesRegex(RuntimeError, "interrupted migration"):
                _db.ensure_store()
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(migrate.current_version(conn), 5)
            self.assertNotIn("direction", {r[1] for r in conn.execute("PRAGMA table_info(items)")})
        _db.ensure_store()
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(migrate.current_version(conn), 6)


    def graph(self, sid, sender="me@example.com", recipients=("dana@example.com",), **over):
        message = {"id": sid, "from": {"emailAddress": {"address": sender, "name": sender}},
                   "toRecipients": [{"emailAddress": {"address": key, "name": key}} for key in recipients],
                   "conversationId": "thread", "parentFolderId": "sent-folder",
                   "sentDateTime": "2026-09-01T01:00:00Z", "receivedDateTime": "2026-09-01T02:00:00Z",
                   "body": {"content": "user-authored words"}}
        message.update(over)
        return normalize.graph_message_to_item(message, "me@example.com", direction=(
            "outbound" if sender == "me@example.com" else "inbound"), source_account="me@example.com")

    def test_graph_preserves_author_and_records_recipient_separately(self):
        row = self.graph("sent")
        self.assertEqual(row["sender_key"], "me@example.com")
        self.assertEqual(row["counterparty_key"], "dana@example.com")
        self.assertEqual(row["counterparty_basis"], "single_recipient")
        self.assertEqual(row["event_at"], "2026-09-01T01:00:00Z")
        self.assertIsNone(row["addressing"])

    def test_all_email_recipients_are_considered_before_attribution(self):
        row = self.graph("group", ccRecipients=[{"emailAddress": {"address": "pat@example.com"}}])
        self.assertIsNone(row["counterparty_key"])
        self.assertEqual(json.loads(row["counterparty_candidates"]), ["dana@example.com", "pat@example.com"])
        self.assertEqual(row["counterparty_pending_until"], "2026-09-08T01:00:00Z")
        self.assertIsNone(self.graph("self", recipients=("me@example.com",))["counterparty_key"])

    def test_opt_ins_are_independent_and_invalid_values_fail_closed(self):
        self.assertFalse(outbound.enabled("email"))
        self.assertFalse(outbound.enabled("slack"))
        with patch.dict(os.environ, {"INTAKE_GRAPH_SENT_ITEMS": "1"}):
            self.assertTrue(outbound.enabled("email"))
            self.assertFalse(outbound.enabled("slack"))
        with patch.dict(os.environ, {"INTAKE_GRAPH_SENT_ITEMS": "yes"}):
            with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
                outbound.enabled("email")

    def test_outbound_memory_evidence_keeps_its_authorship(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        incoming = self.graph("received", sender="dana@example.com", recipients=("me@example.com",))
        sent = [self.graph("sent1"), self.graph("sent2")]
        for row in [incoming] + sent:
            row["event_at"] = now
        with _db.write_txn() as conn:
            normalize.insert_items(conn, [incoming] + sent)
            report = select_memory.evidence(conn, "2026-01-01T00:00:00Z")
        self.assertEqual(len(report["people"]), 1)
        self.assertTrue(report["people"][0]["both_directions"])
        self.assertEqual(report["people"][0]["identities"], ["email:dana@example.com"])
        evidence = next(iter(report["interactions"].values()))
        self.assertEqual({r["direction"] for r in evidence}, {"inbound", "outbound"})

    def test_email_reply_resolution_requires_recipient_account_and_deadline(self):
        cases = [("valid", "me@example.com", "dana@example.com", "2026-09-02T00:00:00Z", True),
                 ("account", "other@example.com", "dana@example.com", "2026-09-02T00:00:00Z", False),
                 ("recipient", "me@example.com", "stranger@example.com", "2026-09-02T00:00:00Z", False),
                 ("late", "me@example.com", "dana@example.com", "2026-09-09T00:00:00Z", False)]
        for label, account, sender, at, expected in cases:
            with self.subTest(label=label), _db.write_txn() as conn:
                conn.execute("DELETE FROM items")
                sent = self.graph("sent", recipients=("dana@example.com", "pat@example.com"))
                reply = self.graph("reply", sender=sender, recipients=("me@example.com",),
                                   receivedDateTime=at, parentFolderId="inbox-folder")
                reply["source_account"] = account
                normalize.insert_items(conn, [sent, reply])
                self.assertEqual(outbound.resolve_pending(conn, "2026-09-10T00:00:00Z"), int(expected))
                row = conn.execute("SELECT sender_key, counterparty_key, counterparty_basis FROM items WHERE source_id='sent'").fetchone()
                self.assertEqual(row[0], "me@example.com")
                self.assertEqual(row[1], "dana@example.com" if expected else None)
                self.assertEqual(row[2], "reply" if expected else None)

    def test_slack_reply_resolution_is_scoped_to_the_user_authored_root(self):
        for channel, expected in (("COTHER", False), ("CEXAMPLE", True)):
            with self.subTest(channel=channel), _db.write_txn() as conn:
                conn.execute("DELETE FROM items")
                sent = normalize.slack_message_to_item({"user": "UME", "ts": "1700000000", "text": "question"},
                    {"id": "CEXAMPLE", "type": "channel"}, "UME", direction="outbound", source_account="T:UME")
                reply = normalize.slack_message_to_item({"user": "UDANA", "ts": "1700000010", "thread_ts": "1700000000", "text": "reply"},
                    {"id": channel, "type": "channel"}, "UME", direction="inbound", source_account="T:UME")
                normalize.insert_items(conn, [sent, reply])
                self.assertEqual(outbound.resolve_pending(conn), int(expected))

    def test_exclusions_cover_recipients_and_unknown_group_members(self):
        (self.home / "workspace" / "exclusions.json").write_text(json.dumps({"senders": ["pat@example.com"]}))
        mail = self.graph("sent", bccRecipients=[{"emailAddress": {"address": "pat@example.com"}}])
        chat = normalize.slack_message_to_item({"user": "UME", "ts": "1700000000", "text": "question"},
            {"id": "CEXAMPLE", "type": "channel"}, "UME", direction="outbound")
        with _db.write_txn() as conn, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(normalize.insert_items(conn, [mail, chat]), 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)

    def test_new_exclusions_prevent_later_counterparty_attribution(self):
        with _db.write_txn() as conn:
            sent = self.graph("sent", recipients=("dana@example.com", "pat@example.com"))
            reply = self.graph("reply", sender="dana@example.com", receivedDateTime="2026-09-02T00:00:00Z")
            normalize.insert_items(conn, [sent, reply])
        (self.home / "workspace" / "exclusions.json").write_text(json.dumps({"senders": ["dana@example.com"]}))
        with _db.write_txn() as conn:
            self.assertEqual(outbound.resolve_pending(conn), 0)
            self.assertIsNone(conn.execute("SELECT counterparty_key FROM items WHERE source_id='sent'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
