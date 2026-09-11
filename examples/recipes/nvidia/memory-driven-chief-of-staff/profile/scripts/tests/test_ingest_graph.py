# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Graph collector, against a stand-in Graph.

These run the real module against a local HTTP server that answers the way
Microsoft Graph does, including the parts that only matter when something goes
wrong: an expired delta cursor, a page that arrives without a cursor of any
kind, a removal that is a move rather than a deletion. Those are exactly the
paths a test that reads the source cannot see.

The delta protocol is what most of this is about. A cursor is opaque and is
only issued when a round completes, so several properties this collector needs
— a partial crawl not advancing the watermark, an interrupted round resuming
rather than restarting — are properties of how the cursor is handled rather
than of arithmetic anybody could check by reading.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sqlite3
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import ingest_graph  # noqa: E402

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")

ME = "avery@example.com"
PLACEHOLDER = "openshell:resolve:env:v1_MS_GRAPH_ACCESS_TOKEN"


def message(mid, *, when="2026-08-20T09:00:00Z", sender="Dana Okoro",
            address="dana@example.com", subject="about the cutover",
            body="the window is Thursday"):
    return {
        "id": mid,
        "receivedDateTime": when,
        "subject": subject,
        "body": {"contentType": "text", "content": body},
        "from": {"emailAddress": {"name": sender, "address": address}},
        "toRecipients": [{"emailAddress": {"address": ME}}],
        "ccRecipients": [],
        "isRead": False,
        "parentFolderId": "inbox",
        "conversationId": "c1",
        "webLink": "https://outlook.example/" + mid,
        "internetMessageId": "<%s@example.com>" % mid,
    }


def sent(mid, *, when="2026-08-20T09:05:00Z", to=None,
         subject="re: cutover", body="sending the doc now"):
    """A Sent Items message: `from` is the mailbox owner, not a counterparty."""
    return {
        "id": mid,
        "receivedDateTime": when,
        "subject": subject,
        "body": {"contentType": "text", "content": body},
        "from": {"emailAddress": {"name": "Avery", "address": ME}},
        "toRecipients": (
            [{"emailAddress": {"name": "Dana Okoro",
                               "address": "dana@example.com"}}]
            if to is None else to),
        "ccRecipients": [],
        "isRead": False,
        "parentFolderId": "sentitems",
        "conversationId": "c1",
        "webLink": "https://outlook.example/" + mid,
        "internetMessageId": "<%s@example.com>" % mid,
    }


def removed(mid):
    """What a delta page carries for something that left the folder.

    Always `deleted`, whether the message was deleted or filed elsewhere —
    measured against the live service, where moving one to Archive produces
    exactly this. An earlier version of these tests invented a `changed`
    reason for a move; no such value exists, so the collector's handling of
    moves was asserted against a payload Graph never sends.
    """
    return {"id": mid, "@removed": {"reason": "deleted"}}


class FakeGraph:
    """A Graph that answers from a script, and records what it was asked."""

    def __init__(self, pages):
        # `pages` is a list of dicts, served in order for successive delta
        # requests against `inbox` — the only folder a test's `serve()` call
        # seeds directly. `sentitems` starts empty, which is what makes it
        # answer "nothing new, synced" the moment it is asked, unless a test
        # calls `queue(..., folder="sentitems")`.
        #
        # Kept as two separate queues, not one shared list split by request
        # order: a shared list would let `sentitems`'s request (issued after
        # `inbox`'s round, every tick) silently consume pages `inbox` queued
        # for its own continuation but had not reached yet — corrupting an
        # exhausted-budget test in a way its own assertions might not catch,
        # while a *resumed* round's test absolutely would.
        self.pages_by_folder: dict[str, list[dict]] = {
            "inbox": list(pages), "sentitems": []}
        # An opaque continuation link (`nextLink`/`deltaLink`) carries no
        # folder marker of its own — real Graph does not put one in a URL a
        # caller is required to treat as opaque, and this fake mirrors that.
        # So the fake remembers, for every link it has ever served, which
        # folder's queue that link continues — populated the moment a page
        # carrying that link is served, looked up the moment it is requested.
        # This is what lets a *resumed* round (a later `run_main()` call,
        # starting directly from a saved opaque URL, never touching the
        # literal `/mailFolders/<folder>/…` path again) still route
        # correctly, even after the other folder's own literal request has
        # run in between.
        self._link_folder: dict[str, str] = {}
        self._last_folder = "inbox"
        self.calls: list[str] = []
        self.headers_seen: list[str] = []
        self.identity = {"mail": ME, "displayName": "Avery"}
        self.status_for_next = None
        # Whether a message that left the folder is still somewhere in the
        # mailbox. `True` is a move, `False` is a deletion — the service tells
        # them apart no other way.
        self.still_present = False
        self.identity_lookups = 0
        self.rate_limit_forever = False
        # The removal lookup answers before the rate-limit branch, so it needs
        # knobs of its own to be made slow or made to fail.
        self.rate_limit_lookups = False
        self.lookup_status = None
        # Throttle each request this many times, then let it through. Unlike
        # `rate_limit_forever` this lets a tick make several requests, which
        # is the only way a per-request bound and a per-tick one differ.
        self.throttle_per_request = 0
        self.throttled_since_success = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: A003
                pass

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                outer.calls.append(self.path)
                outer.headers_seen.append(self.headers.get("Authorization", ""))

                if parsed.path.endswith("/me"):
                    return outer._send(self, 200, outer.identity)

                if parsed.path.endswith("/messages") and "filter" in self.path:
                    # The "is it still in the mailbox" question, asked by
                    # `internetMessageId` when something leaves the folder.
                    outer.identity_lookups += 1
                    if outer.lookup_status is not None:
                        return outer._send(self, outer.lookup_status,
                                           {"error": {"code": "x"}})
                    if outer.rate_limit_lookups:
                        body = json.dumps(
                            {"error": {"code": "throttled"}}).encode()
                        self.send_response(429)
                        self.send_header("Retry-After", "1")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    hits = [{"id": "elsewhere"}] if outer.still_present else []
                    return outer._send(self, 200, {"value": hits})

                throttling = outer.rate_limit_forever or (
                    outer.throttled_since_success < outer.throttle_per_request)
                if throttling:
                    outer.throttled_since_success += 1
                    body = json.dumps({"error": {"code": "throttled"}}).encode()
                    self.send_response(429)
                    self.send_header("Retry-After", "1")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                outer.throttled_since_success = 0

                if outer.status_for_next is not None:
                    code = outer.status_for_next
                    outer.status_for_next = None
                    return outer._send(self, code, {"error": {"code": "x"}})

                folder = outer._folder_for(parsed.path)
                queue = outer.pages_by_folder.setdefault(folder, [])
                if queue:
                    served = queue.pop(0)
                    for key in ("@odata.nextLink", "@odata.deltaLink"):
                        link = served.get(key)
                        if link:
                            outer._link_folder[urlparse(link).path] = folder
                    return outer._send(self, 200, served)
                link = f"{outer.url}/{folder}-delta-final"
                outer._link_folder[urlparse(link).path] = folder
                return outer._send(self, 200, {
                    "value": [], "@odata.deltaLink": link})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def _send(handler, status, payload):
        body = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _folder_for(self, path: str) -> str:
        """Which folder's queue this request continues.

        The literal first-round path names its folder unambiguously and is
        trusted first. Anything else is an opaque continuation link: looked
        up by the folder it was tagged with when this fake served it, since
        the path itself carries no folder marker (see `__init__`). A path
        this fake has never seen before — a test-authored `http://x/…`
        constant that was never returned as a `nextLink`/`deltaLink` value —
        falls back to whichever folder was resolved most recently, which is
        always correct for a same-round follow-up request.
        """
        if "/mailFolders/sentitems/" in path:
            self._last_folder = "sentitems"
        elif "/mailFolders/inbox/" in path:
            self._last_folder = "inbox"
        elif path in self._link_folder:
            self._last_folder = self._link_folder[path]
        return self._last_folder

    def queue(self, *pages, folder="inbox"):
        """Add pages for later rounds, on the same server.

        Stopping one stand-in and starting another leaves the saved cursor
        pointing at a dead address, which hangs rather than failing — so the
        whole of a multi-round test runs against one server.
        """
        self.pages_by_folder.setdefault(folder, []).extend(json.loads(
            json.dumps(list(pages)).replace("http://x/", self.url + "/")))

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1.0"

    def stop(self):
        self.server.shutdown()

    def delta_requests(self):
        return [c for c in self.calls if "/delta" in c or "delta-" in c]


class CollectorCase(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        env = patch.dict(os.environ, {"INTAKE_GRAPH_SENT_ITEMS": "0", "INTAKE_SLACK_SELF_AUTHORED": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.home = tempfile.mkdtemp()
        Path(self.home, "distribution.yaml").write_text("id: t\n",
                                                        encoding="utf-8")
        Path(self.home, "workspace", "ledger").mkdir(parents=True)
        self.db = Path(self.home) / "workspace" / "ledger" / "state.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
        os.environ["HERMES_HOME"] = self.home
        os.environ["MS_GRAPH_ACCESS_TOKEN"] = PLACEHOLDER
        self.graph = None
        self._api = ingest_graph.API

    def tearDown(self):
        if self.graph:
            self.graph.stop()
        ingest_graph.API = self._api
        for name in ("MS_GRAPH_ACCESS_TOKEN", "GRAPH_BACKFILL_DAYS"):
            os.environ.pop(name, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def serve(self, pages):
        """Start a stand-in Graph and point the collector at it.

        Links in the scripted pages are written as `http://x/…` and rewritten
        to this server's address here. A cursor pointing at a host that does
        not exist is not a cursor — the collector would follow it, fail to
        connect, and the test would be measuring the fake rather than the
        code.
        """
        self.graph = FakeGraph(pages)
        ingest_graph.API = self.graph.url
        for folder, queued in self.graph.pages_by_folder.items():
            self.graph.pages_by_folder[folder] = json.loads(
                json.dumps(queued).replace("http://x/", self.graph.url + "/"))
        return self.graph

    def run_main(self, args=None):
        """Call the collector without its stdout landing in the test report."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ingest_graph.main(args or [])
        self.stdout = buffer.getvalue()
        return code

    def run_main_recording_waits(self, args=None):
        """Run a tick, recording every sleep it asks for instead of taking it.

        Taking them would make this test wait out the real budget, which is
        two minutes by design. What is under test is the arithmetic across
        requests, and that is visible without the waiting.
        """
        recorded: list[float] = []
        real_sleep = ingest_graph.time.sleep
        ingest_graph.time.sleep = recorded.append
        try:
            code = self.run_main(args)
        finally:
            ingest_graph.time.sleep = real_sleep
        return code, recorded

    def report(self):
        return json.loads(self.stdout)

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT source_id, sender, body, deleted_at, body_cleared_at"
                "  FROM items ORDER BY source_id").fetchall()

    def outbound_row(self, source_id=None):
        query = ("SELECT counterparty_name, counterparty_key, addressing, unread, direction,"
                 " counterparty_pending_until FROM items")
        args: tuple = ()
        if source_id is not None:
            query += " WHERE source_id = ?"
            args = (source_id,)
        with sqlite3.connect(self.db) as conn:
            return conn.execute(query, args).fetchone()

    def state(self):
        return ingest_graph.read_state()

    def folder_state(self, folder="inbox"):
        return self.state().get("folders", {}).get(folder, {})


class TestAFetchWritesRowsTheNormalizerMade(CollectorCase):
    def test_messages_reach_the_store(self):
        self.serve([{"value": [message("m1"), message("m2")],
                     "@odata.deltaLink": "http://x/final"}])
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OK)
        self.assertEqual([r[0] for r in self.rows()], ["m1", "m2"])

    def test_the_row_is_what_the_normalizer_makes(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        row = self.rows()[0]
        self.assertEqual(row[1], "Dana Okoro")
        self.assertIn("Thursday", row[2])

    def test_a_second_run_is_idempotent(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"},
                    {"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.run_main()
        self.assertEqual(len([r for r in self.rows() if r[0] == "m1"]), 1)

    def test_the_report_says_what_it_did(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        found = self.report()
        self.assertEqual(found["added"], 1)
        self.assertTrue(found["complete"])
        self.assertTrue(found["synchronised"])


class TestDeletionIsReconciled(CollectorCase):
    """#122 decision 4: Graph reports deletions, so they are acted on at once
    rather than waiting for the retention pass."""

    def stored(self, mid="m1"):
        """One message in the store, and the stand-in still running."""
        self.serve([{"value": [message(mid)],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()

    def test_a_deleted_message_is_tombstoned(self):
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        row = self.rows()[0]
        self.assertIsNotNone(row[3], "deleted_at was not set")

    def test_its_body_goes_at_once(self):
        """Not at the next retention pass: the person said what they want."""
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        row = self.rows()[0]
        self.assertIsNone(row[2], "the body survived a deletion")
        self.assertIsNotNone(row[4])

    def test_the_row_survives(self):
        """Obligations and events hang off `source_id`; deleting the row would
        break the audit trail that explains why something was ranked."""
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        self.assertEqual([r[0] for r in self.rows()], ["m1"])

    def test_metadata_survives_the_tombstone(self):
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        self.assertEqual(self.rows()[0][1], "Dana Okoro")

    def test_a_message_filed_elsewhere_is_not_a_deletion(self):
        """Graph reports a move out of the folder exactly as it reports a
        deletion, and the per-folder id changes so it cannot answer either.
        What survives a move is `internetMessageId`; if the mailbox still
        holds it, the message was filed rather than deleted."""
        self.stored()
        self.graph.still_present = True
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        row = self.rows()[0]
        self.assertIsNone(row[3], "a filed message was tombstoned")
        self.assertIsNotNone(row[2], "a filed message lost its body")
        self.assertEqual(self.report()["moved"], 1)
        self.assertEqual(self.report()["removed"], 0)

    def test_the_question_is_actually_asked(self):
        """Without the lookup the two cases are indistinguishable, so a test
        that never sees the request is not testing the distinction."""
        self.stored()
        self.graph.still_present = True
        before = self.graph.identity_lookups
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        self.assertGreater(self.graph.identity_lookups, before)

    def test_a_message_gone_from_the_mailbox_is_a_deletion(self):
        self.stored()
        self.graph.still_present = False
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        row = self.rows()[0]
        self.assertIsNotNone(row[3])
        self.assertIsNone(row[2])

    def test_the_report_counts_removals(self):
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        self.assertEqual(self.report()["removed"], 1)

    def test_tombstoning_twice_counts_once(self):
        """A repeated delta page must not keep rewriting the timestamp."""
        self.stored()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/f2"},
                         {"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/f3"})
        self.run_main()
        first = self.rows()[0][3]
        self.run_main()
        self.assertEqual(self.rows()[0][3], first)
        self.assertEqual(self.report()["removed"], 0)


class TestTheCursorIsTheWatermark(CollectorCase):
    """A delta cursor is only issued when a round completes, so a partial
    crawl cannot advance it — the property is the protocol's, not this
    module's, and that is the reason for using it."""

    def test_a_completed_round_stores_a_delta_cursor(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertIn("delta", self.folder_state())
        self.assertNotIn("next", self.folder_state())

    def test_an_interrupted_round_stores_the_page_instead(self):
        pages = [{"value": [message(f"m{i}")],
                  "@odata.nextLink": f"http://x/page{i + 1}"}
                 for i in range(ingest_graph.REQUEST_BUDGET + 2)]
        self.serve(pages)
        self.run_main()
        self.assertIn("next", self.folder_state())
        self.assertNotIn("delta", self.folder_state(),
                         "a partial crawl recorded a synchronisation point")
        self.assertFalse(self.report()["complete"])

    def test_the_next_tick_resumes_rather_than_restarting(self):
        pages = [{"value": [message(f"m{i}")],
                  "@odata.nextLink": f"http://x/page{i + 1}"}
                 for i in range(ingest_graph.REQUEST_BUDGET + 2)]
        pages.append({"value": [message("last")],
                      "@odata.deltaLink": "http://x/final"})
        self.serve(pages)
        self.run_main()
        resumed_from = self.folder_state()["next"]
        self.run_main()
        self.assertIn(resumed_from.rsplit("/", 1)[-1],
                      "".join(self.graph.calls),
                      "the second tick did not continue from the saved page")
        self.assertTrue(self.report()["resumed"])

    def test_rows_from_an_interrupted_round_are_kept(self):
        """Partial progress is still progress; the rows are idempotent."""
        pages = [{"value": [message(f"m{i}")],
                  "@odata.nextLink": f"http://x/page{i + 1}"}
                 for i in range(ingest_graph.REQUEST_BUDGET + 2)]
        self.serve(pages)
        self.run_main()
        self.assertTrue(self.rows())

    def test_a_page_with_neither_link_does_not_record_a_position(self):
        """Graph gave nothing to resume from, so there is nothing to save."""
        self.serve([{"value": [message("m1")]}])
        self.run_main()
        self.assertNotIn("next", self.folder_state())
        self.assertNotIn("delta", self.folder_state())
        self.assertFalse(self.report()["complete"])

    def test_an_expired_cursor_starts_a_fresh_round(self):
        """Graph expires an unused cursor with 410, and the recovery is a new
        round rather than a failed run."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.graph.queue({"value": [message("m2")],
                          "@odata.deltaLink": "http://x/final2"})
        self.graph.status_for_next = 410
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OK)
        self.assertTrue(self.report().get("resynchronised"))
        self.assertIn("m2", [r[0] for r in self.rows()])


class TestSentItemsIsSynchronisedInItsOwnRight(CollectorCase):
    """Sent Items gets its own delta cursor and its own full page budget --
    not a filter over the inbox round, a second independent round."""

    def setUp(self):
        super().setUp()
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"

    def test_a_single_recipient_message_resolves_immediately(self):
        self.serve([])
        self.graph.queue({"value": [sent("s1")],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        sender, key, addressing, unread, direction, pending = (
            self.outbound_row("s1"))
        self.assertEqual(sender, "Dana Okoro")
        self.assertEqual(key, "dana@example.com")
        self.assertIsNone(addressing)
        self.assertIsNone(unread)
        self.assertEqual(direction, "outbound")
        self.assertIsNone(pending)

    def test_more_than_one_recipient_leaves_the_counterparty_pending(self):
        self.serve([])
        self.graph.queue({"value": [sent("s1", to=[
            {"emailAddress": {"name": "Dana Okoro",
                              "address": "dana@example.com"}},
            {"emailAddress": {"name": "Jae Park",
                              "address": "jae@example.com"}}])],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        sender, key, _addr, _unread, direction, pending = self.outbound_row("s1")
        self.assertIsNone(sender)
        self.assertIsNone(key)
        self.assertEqual(direction, "outbound")
        self.assertIsNotNone(pending)

    def test_inbox_rows_are_still_inbound(self):
        """Direction handling for one folder must not disturb the other."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.graph.queue({"value": [sent("s1")],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        _sender, _key, _addr, _unread, direction, pending = (
            self.outbound_row("m1"))
        self.assertEqual(direction, "inbound")
        self.assertIsNone(pending)

    def test_each_folder_keeps_its_own_delta_cursor(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/inbox-final"}])
        self.graph.queue({"value": [sent("s1")],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        self.assertIn("inbox-final", self.folder_state("inbox")["delta"])
        self.assertIn("sent-final", self.folder_state("sentitems")["delta"])

    def test_the_report_nests_sentitems_under_its_own_key(self):
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/inbox-final"}])
        self.graph.queue({"value": [sent("s1")],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        found = self.report()
        # Inbox's own fields stay at the top level, unchanged in shape from
        # before Sent Items existed.
        self.assertEqual(found["added"], 1)
        self.assertEqual(found["sentitems"]["added"], 1)
        self.assertTrue(found["sentitems"]["complete"])

    def test_a_large_inbox_backlog_does_not_delay_sentitems_own_turn(self):
        """Each folder gets its own full REQUEST_BUDGET, not a shared pool --
        an exhausted inbox round must not leave sentitems unserved."""
        pages = [{"value": [message(f"m{i}")],
                  "@odata.nextLink": f"http://x/page{i + 1}"}
                 for i in range(ingest_graph.REQUEST_BUDGET + 2)]
        self.serve(pages)
        self.graph.queue({"value": [sent("s1")],
                          "@odata.deltaLink": "http://x/sent-final"},
                         folder="sentitems")
        self.run_main()
        self.assertFalse(self.report()["complete"],
                         "the inbox round should still be interrupted")
        self.assertTrue(self.report()["sentitems"]["complete"],
                        "sentitems did not get its own turn this tick")
        self.assertEqual([r[0] for r in self.rows() if r[0] == "s1"], ["s1"])

    def test_a_legacy_flat_state_file_migrates_to_folders_inbox(self):
        """A pre-Phase-C state file names the inbox round implicitly -- there
        was no other folder to name. Upgrading must not discard its cursor."""
        Path(self.home, "workspace", "graph_state.json").write_text(
            json.dumps({"delta": "http://x/legacy-delta",
                       "identity": {"address": ME, "display_name": "Avery"}}),
            encoding="utf-8")
        state = ingest_graph.read_state()
        self.assertEqual(state["folders"]["inbox"]["delta"],
                         "http://x/legacy-delta")
        self.assertEqual(state["identity"]["address"], ME)


class TestSentItemsOptIn(CollectorCase):
    def test_own_inbox_copy_does_not_duplicate_sent_evidence(self):
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([{"value": [sent("inbox-copy")]}])
        self.graph.queue({"value": [sent("sent-copy")]}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual([row[0] for row in self.rows()], ["sent-copy"])

    def test_default_off_makes_no_sent_requests_even_when_slack_is_enabled(self):
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "1"
        self.serve([{"value": [message("in"), sent("self-copy")], "@odata.deltaLink": "http://x/inbox-final"}])
        self.graph.queue({"value": [sent("sent")]}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual([row[0] for row in self.rows()], ["in"])
        self.assertFalse(any("sentitems" in url for url in self.graph.calls))
        self.assertFalse(self.report()["sentitems"]["enabled"])

    def test_invalid_opt_in_stops_before_any_request(self):
        self.serve([])
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "yes"
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)
        self.assertEqual(self.graph.calls, [])

    def test_disabling_preserves_sent_cursor_and_reenabling_resumes_it(self):
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([])
        self.graph.queue({"value": [sent("s1")], "@odata.deltaLink": "http://x/sent-cursor"}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        prior = self.folder_state("sentitems")
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "0"
        self.graph.calls.clear()
        self.graph.queue({"value": [sent("s2")], "@odata.deltaLink": "http://x/sent-next"}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.folder_state("sentitems"), prior)
        self.assertFalse(any("sent" in url for url in self.graph.calls))
        self.assertEqual(len(self.rows()), 1)
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.graph.calls.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertTrue(any("sent-cursor" in url for url in self.graph.calls))
        self.assertEqual(len(self.rows()), 2)

    def test_sent_folder_does_not_prove_user_authorship(self):
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([])
        self.graph.queue({"value": [message("copied-other-person")], "@odata.deltaLink": "http://x/sent-final"}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.report()["sentitems"]["unverified_authorship"], 1)

    def test_primary_name_alias_is_known_but_other_aliases_are_not_guessed(self):
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([])
        alias = "alias@example.com"
        self.graph.identity["userPrincipalName"] = alias
        entry = sent("alias")
        entry["from"]["emailAddress"]["address"] = alias
        self.graph.queue({"value": [entry], "@odata.deltaLink": "http://x/sent-final"}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT sender_key, direction, source_account FROM items").fetchone(),
                             (alias, "outbound", ME))

    def test_inbox_progress_survives_a_sent_folder_failure(self):
        from unittest.mock import patch
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([{"value": [message("in")], "@odata.deltaLink": "http://x/inbox-final"}])
        collect = ingest_graph.collect
        def fail_sent(token, address, state, days, budget, folder, **kwargs):
            if folder == "sentitems":
                raise ingest_graph.GraphError("fixture failure")
            return collect(token, address, state, days, budget, folder, **kwargs)
        with patch.object(ingest_graph, "collect", side_effect=fail_sent):
            self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)
        self.assertIn("inbox-final", self.folder_state("inbox")["delta"])
        self.assertEqual(len(self.rows()), 1)

    def test_bcc_exclusion_applies_before_any_sent_body_is_stored(self):
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.serve([])
        Path(self.home, "workspace", "exclusions.json").write_text(json.dumps({"domains": ["private.example"]}))
        entry = sent("s1")
        entry["bccRecipients"] = [{"emailAddress": {"address": "person@private.example"}}]
        self.graph.queue({"value": [entry], "@odata.deltaLink": "http://x/sent-final"}, folder="sentitems")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.rows(), [])

    def test_failed_state_publication_keeps_the_previous_complete_snapshot(self):
        from unittest.mock import patch
        self.serve([{"value": [], "@odata.deltaLink": "http://x/inbox-first"}])
        self.assertEqual(self.run_main(), 0)
        original = ingest_graph.state_path().read_bytes()
        self.graph.queue({"value": [message("new")], "@odata.deltaLink": "http://x/inbox-second"})
        with patch.object(ingest_graph.os, "replace", side_effect=OSError("fixture failure")):
            self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)
        self.assertEqual(ingest_graph.state_path().read_bytes(), original)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(list(ingest_graph.state_path().parent.glob(".graph-state-*")), [])

    def test_malformed_cursor_state_is_reported_without_collection(self):
        self.serve([])
        ingest_graph.state_path().write_text('{"folders":{"inbox":[]}}')
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)
        self.assertEqual(self.graph.calls, [])


class TestTheMailboxIdentityIsChecked(CollectorCase):
    """Inside the sandbox the credential is a placeholder the gateway
    substitutes, and it does not change when the token behind it does."""

    def test_a_changed_mailbox_discards_the_previous_cursor(self):
        """The cursor is the thing that must not carry over.

        Asserting that the recorded address changed proves nothing: it is
        written on every run regardless. What matters is that a cursor issued
        for one mailbox is not used to ask another what has changed.
        """
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/first-mailbox"}])
        self.run_main()
        first_cursor = self.folder_state()["delta"]
        self.assertIn("first-mailbox", first_cursor)

        self.graph.identity = {"mail": "someone.else@example.com",
                               "displayName": "Someone Else"}
        self.graph.calls.clear()
        self.graph.queue({"value": [message("m2")],
                          "@odata.deltaLink": "http://x/second-mailbox"})
        self.run_main()

        followed = [c for c in self.graph.calls if "first-mailbox" in c]
        self.assertEqual(followed, [],
                         "asked the new mailbox what changed since the old "
                         "one's cursor")
        self.assertIn("/delta?", "".join(self.graph.calls),
                      "did not start a fresh round for the new mailbox")

    def test_a_changed_mailbox_does_not_answer_removals_from_the_old_one(self):
        """Message identities used to live in a map beside the cursor, and
        the map had to be discarded with it. They now live on the row, where
        the question is which mailbox a row belongs to.

        Graph ids are per-mailbox, so a removal reported by the new mailbox
        names an id the store has never seen. That is the `unknown` case: no
        row is tombstoned, and the old mailbox's messages are left exactly as
        they were rather than being resolved against a different inbox.
        """
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()

        self.graph.identity = {"mail": "someone.else@example.com"}
        self.graph.queue({"value": [removed("other-mailbox-id")],
                          "@odata.deltaLink": "http://x/f2"})
        self.graph.still_present = False
        before = self.graph.identity_lookups
        self.assertEqual(self.run_main(), 0)

        # No request was made, because there was nothing to ask about.
        self.assertEqual(self.graph.identity_lookups, before)
        # rows() is (source_id, sender, body, deleted_at, body_cleared_at)
        self.assertEqual([r[0] for r in self.rows()], ["m1"])
        self.assertIsNone(self.rows()[0][3],
                          "a row was tombstoned by another mailbox's removal")
        self.assertEqual(self.report()["unresolved_removals"], 1)

    def test_the_placeholder_staying_the_same_does_not_hide_it(self):
        """The credential is byte-identical across the change; only the
        mailbox differs, so only the mailbox can be compared."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        before = os.environ["MS_GRAPH_ACCESS_TOKEN"]
        self.graph.identity = {"mail": "other@example.com"}
        self.graph.queue({"value": [], "@odata.deltaLink": "http://x/f2"})
        self.run_main()
        self.assertEqual(os.environ["MS_GRAPH_ACCESS_TOKEN"], before)
        self.assertEqual(self.state()["identity"]["address"],
                         "other@example.com")

    def test_the_same_mailbox_keeps_its_cursor(self):
        """Re-checking must not become re-synchronising every tick."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        first = self.folder_state()["delta"]
        self.graph.queue({"value": [], "@odata.deltaLink": "http://x/final"})
        self.run_main()
        self.assertEqual(self.folder_state()["delta"], first)


class TestTheScopesAreTheOnesUsed(CollectorCase):
    """A setup that depends on a permission it does not request is a setup
    that works for whoever already had it."""

    RECIPE = HERE.parents[1]

    def scopes_requested(self):
        """The `SCOPES=` line, not the whole file.

        Searching the file finds the comment explaining why `User.Read` is
        needed, which stays true whether or not the flow asks for it — so the
        first version of this passed with the scope deleted.
        """
        setup = (self.RECIPE / "scripts" / "setup-graph.sh").read_text(
            encoding="utf-8")
        line = [l for l in setup.splitlines() if l.startswith("SCOPES=")]
        self.assertEqual(len(line), 1, "expected exactly one SCOPES= line")
        return line[0]

    def test_user_read_is_requested_because_me_is_read(self):
        collector = (HERE / "ingest_graph.py").read_text(encoding="utf-8")
        self.assertIn("/me?", collector)
        self.assertIn("User.Read", self.scopes_requested())

    def test_the_profile_refreshes_with_named_scopes(self):
        """`.default` returns whatever the client already has, which is more
        than this needs and grows as an administrator grants more."""
        profile = (self.RECIPE / "providers" / "graph-user.yaml").read_text(
            encoding="utf-8")
        # Asserted on the scope list rather than on the file, because the file
        # names `.default` in the comment explaining why it is not used —
        # which is worth keeping and is not a use of it.
        block = profile.split("scopes:", 1)[1].split("material:", 1)[0]
        self.assertNotIn(".default", block)
        self.assertIn("Mail.Read", block)
        self.assertIn("User.Read", block)
        self.assertIn("offline_access", block)

    def test_the_setup_and_the_profile_ask_for_the_same_thing(self):
        requested = self.scopes_requested()
        profile = (self.RECIPE / "providers" / "graph-user.yaml").read_text(
            encoding="utf-8")
        block = profile.split("scopes:", 1)[1].split("material:", 1)[0]
        for scope in ("Mail.Read", "User.Read", "offline_access"):
            self.assertIn(scope, requested, scope)
            self.assertIn(scope, block, scope)


class TestTheGraphSetupRefusesAnIncompleteProvider(unittest.TestCase):
    """A provider that attaches cleanly and stops within the hour is worse
    than one that refuses: the setup reports success and the failure arrives
    later, unattended."""

    RECIPE = HERE.parents[1]
    SCRIPT = RECIPE / "scripts" / "setup-graph.sh"

    def fake_openshell(self, folder, *, refresh_ok=True, strategy="oauth2_refresh_token"):
        stub = folder / "openshell"
        status = (f"STRATEGY {strategy} STATUS refreshed"
                  if refresh_ok else "")
        rc = "0" if refresh_ok else "1"
        profile = json.dumps({
            "id": "memory-driven-cos-graph-user",
            "endpoints": [{"host": "graph.microsoft.com", "port": 443,
                           "protocol": "rest", "access": "read-only",
                           "enforcement": "enforce"}],
            "credentials": [{"env_vars": ["MS_GRAPH_ACCESS_TOKEN"]}],
            "binaries": ["/usr/bin/python3"]})
        stub.write_text(f"""#!/usr/bin/env bash
case "$1 $2" in
  "sandbox provider") cat <<'LIST'
NAME  TYPE  CREDENTIAL_KEYS
mdcos-graph  memory-driven-cos-graph-user  1
LIST
  ;;
  "provider get") printf 'Type: memory-driven-cos-graph-user\nCredential keys: MS_GRAPH_ACCESS_TOKEN\n' ;;
  "provider refresh") printf '%s\n' {status!r}; exit {rc} ;;
  "provider profile") cat <<'JSON'
{profile}
JSON
  ;;
  *) exit 0 ;;
esac
""", encoding="utf-8")
        stub.chmod(0o755)
        uname = folder / "uname"
        uname.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
        uname.chmod(0o755)
        return folder

    def run_setup(self, folder):
        return subprocess.run(
            ["bash", str(self.SCRIPT)], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, cwd=str(self.RECIPE),
            env={"PATH": f"{folder}:{os.environ['PATH']}",
                 "HOME": str(folder), "OPENSHELL_SANDBOX": "",
                 "SANDBOX_STORAGE_PATH": str(folder),
                 "STORE_ENCRYPTION_ACKNOWLEDGED": "1"})

    def test_a_provider_with_refresh_is_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder)
            proc = self.run_setup(folder)
        self.assertIn("Nothing to do", proc.stdout)

    def test_a_provider_without_refresh_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder, refresh_ok=False)
            proc = self.run_setup(folder)
        out = proc.stdout + proc.stderr
        self.assertNotIn("Nothing to do", out,
                         "reported a finished setup for a credential that "
                         "would expire within the hour")
        self.assertIn("refresh", out)

    def test_a_provider_with_the_wrong_strategy_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder, strategy="static")
            proc = self.run_setup(folder)
        out = proc.stdout + proc.stderr
        self.assertNotIn("Nothing to do", out)
        self.assertIn("rotation", out)


class TestTheFirstRoundIsBounded(CollectorCase):
    def test_the_window_reaches_the_request(self):
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        os.environ["GRAPH_BACKFILL_DAYS"] = "14"
        self.run_main()
        asked = [c for c in self.graph.calls if "/delta" in c][0]
        self.assertIn("receivedDateTime+ge", asked.replace("%20", "+")
                      .replace("%3E", ">").replace("+ge+", "+ge+"))

    def test_the_default_window_is_the_one_the_docs_state(self):
        self.assertEqual(ingest_graph.BACKFILL_DAYS, 7)

    def test_the_report_says_which_window_was_used(self):
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        os.environ["GRAPH_BACKFILL_DAYS"] = "30"
        self.run_main()
        self.assertEqual(self.report()["backfill_days"], 30)

    def test_a_window_that_synchronises_nothing_is_refused(self):
        for bad in ("0", "-1", "abc",
                    str(ingest_graph.MAX_BACKFILL_DAYS + 1)):
            os.environ["GRAPH_BACKFILL_DAYS"] = bad
            with self.assertRaises(SystemExit):
                ingest_graph.bounded_days("GRAPH_BACKFILL_DAYS",
                                          ingest_graph.BACKFILL_DAYS)

    def test_the_window_applies_only_to_the_first_round(self):
        """The cursor carries no filter, so later rounds report every change —
        including an older message being deleted. Choosing seven days is
        choosing where to start, not choosing to be told less afterwards."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"},
                    {"value": [], "@odata.deltaLink": "http://x/final2"}])
        os.environ["GRAPH_BACKFILL_DAYS"] = "7"
        self.run_main()
        self.graph.calls.clear()
        self.run_main()
        for call in self.graph.calls:
            self.assertNotIn("receivedDateTime", call,
                             "a later round re-applied the first window")


class TestTheCredentialIsNeverEchoed(CollectorCase):
    SECRET = "openshell:resolve:env:v9_DO_NOT_PRINT_THIS"

    def test_it_is_not_in_the_report(self):
        os.environ["MS_GRAPH_ACCESS_TOKEN"] = self.SECRET
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertNotIn("DO_NOT_PRINT_THIS", self.stdout)

    def test_it_is_not_in_the_saved_state(self):
        """The identity cache is keyed on a digest, not on the token."""
        os.environ["MS_GRAPH_ACCESS_TOKEN"] = self.SECRET
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertNotIn("DO_NOT_PRINT_THIS",
                         json.dumps(self.state()))

    def test_it_does_reach_the_service(self):
        """The point is that it is not echoed, not that it is unused."""
        os.environ["MS_GRAPH_ACCESS_TOKEN"] = self.SECRET
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertTrue(any(self.SECRET in h for h in self.graph.headers_seen))


class TestFailuresCarryTheirDiagnosisInTheExitCode(CollectorCase):
    def test_never_configured_is_free(self):
        """This file exists long before most people connect a mailbox; if an
        absent credential were a failure the wake gate would never fire."""
        os.environ.pop("MS_GRAPH_ACCESS_TOKEN", None)
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OK)
        self.assertTrue(json.loads(self.stdout)["unconfigured"])

    def test_a_credential_that_disappeared_is_a_failure(self):
        """A detached provider empties the variable, which then looks exactly
        like never having set one up."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        os.environ.pop("MS_GRAPH_ACCESS_TOKEN", None)
        self.assertEqual(self.run_main(), ingest_graph.EXIT_CREDENTIAL)

    def test_a_refused_credential_says_so(self):
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.graph.status_for_next = 401
        self.assertEqual(self.run_main(), ingest_graph.EXIT_CREDENTIAL)

    def test_an_application_token_is_a_scope_failure(self):
        """No mailbox address means it is not a delegated token, and the
        recipe reads the signed-in mailbox."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.graph.identity = {"displayName": "App"}
        self.assertEqual(self.run_main(), ingest_graph.EXIT_SCOPE)

    def test_an_unrecognised_status_is_the_general_code(self):
        """This test used to be named for rate limiting and sent a 500."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.graph.status_for_next = 500
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)

    def test_relentless_throttling_ends_the_tick(self):
        """A `Retry-After` inside the per-wait bound, over and over, is a loop
        with no exit: the page budget counts successful responses and a cron
        pre-step has no timeout of its own. Reproduced at review as 9,248
        retries still going."""
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.graph.rate_limit_forever = True
        ingest_graph.MAX_TOTAL_BACKOFF_SECONDS = 3
        try:
            self.assertEqual(self.run_main(), ingest_graph.EXIT_RATE_LIMIT)
        finally:
            ingest_graph.MAX_TOTAL_BACKOFF_SECONDS = 120

    def test_the_waiting_bound_belongs_to_the_tick_not_the_request(self):
        """The bound is what one run may spend waiting, in total.

        Held per request it multiplied by the number of requests: a page
        budget of ten turned a two-minute ceiling into twenty minutes in
        `sleep`. Comparing the two constants — which is what this test used to
        do — could not see that, and stayed green throughout.

        Several pages, each throttled for a while and then served, so the
        tick makes more than one request — which is the only arrangement in
        which a per-request bound and a per-tick one differ at all. Each
        request stays inside the per-request bound; together they do not.
        """
        self.serve([{"value": [message("m%d" % n)],
                     "@odata.nextLink": "http://x/p%d" % n}
                    for n in range(4)])
        # Four requests at 40 seconds each: none of them alone exceeds the
        # two-minute bound, and the four together exceed it by a third.
        self.graph.throttle_per_request = 40
        code, waits = self.run_main_recording_waits()
        self.assertEqual(code, ingest_graph.EXIT_RATE_LIMIT)
        self.assertLessEqual(sum(waits),
                             ingest_graph.MAX_TOTAL_BACKOFF_SECONDS)
        # More than one request really was throttled, or the bound above is
        # met by a tick that only ever made one.
        self.assertGreater(len(waits), 40)

    def test_the_budget_already_spent_is_not_refunded_by_a_new_request(self):
        """The unit under the end-to-end test, stated directly."""
        budget = ingest_graph.Budget(seconds=3)
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                ingest_graph.time, "sleep", lambda s: None))
            budget.spend(2)
            with self.assertRaises(ingest_graph.GraphError) as caught:
                budget.spend(2)
        self.assertEqual(caught.exception.kind, "rate_limit")

    def test_throttling_during_a_removal_lookup_is_bounded_too(self):
        """The lookup is a Graph request like any other, and it is the one
        made most often when something has been deleted."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.graph.rate_limit_lookups = True
        code, waits = self.run_main_recording_waits()
        self.assertEqual(code, ingest_graph.EXIT_RATE_LIMIT)
        self.assertLessEqual(sum(waits),
                             ingest_graph.MAX_TOTAL_BACKOFF_SECONDS)

    def test_a_removal_with_no_identity_is_not_read_as_a_deletion(self):
        """The case that cleared a body without contacting Graph at all.

        Identities used to live in a map capped at five thousand entries that
        evicted oldest-first, so filing away an older message produced a
        removal with nothing to ask about — and the absence was read as a
        deletion. A row collected before the column existed is the same
        situation, and is the one that survives the map being gone.
        """
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        # Exactly a v3 row: collected, but with no identity of its own.
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE items SET internet_message_id = NULL")

        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        before = self.graph.identity_lookups
        self.assertEqual(self.run_main(), 0)

        self.assertEqual(self.graph.identity_lookups, before,
                         "asked Graph a question it had no id for")
        self.assertIsNone(self.rows()[0][3],
                          "tombstoned a message it could not ask about")
        self.assertIsNotNone(self.rows()[0][2], "cleared the body anyway")
        self.assertEqual(self.report()["unresolved_removals"], 1)

    def test_an_identity_learned_earlier_in_the_same_round_answers(self):
        """A message collected on one page and removed on a later page of the
        same round. The rows are written before the removals are resolved, so
        the question can be answered without waiting for the next tick."""
        self.serve([
            {"value": [message("m1")], "@odata.nextLink": "http://x/p2"},
            {"value": [removed("m1")], "@odata.deltaLink": "http://x/final"},
        ])
        self.graph.still_present = False
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.graph.identity_lookups, 1,
                         "the identity from the first page was not available")
        self.assertIsNotNone(self.rows()[0][3])
        self.assertEqual(self.report()["unresolved_removals"], 0)

    def test_a_message_moved_in_the_same_round_is_not_a_deletion(self):
        """The other half: same arrangement, and the mailbox still has it."""
        self.serve([
            {"value": [message("m1")], "@odata.nextLink": "http://x/p2"},
            {"value": [removed("m1")], "@odata.deltaLink": "http://x/final"},
        ])
        self.graph.still_present = True
        self.assertEqual(self.run_main(), 0)
        self.assertIsNone(self.rows()[0][3])
        self.assertEqual(self.report()["moved"], 1)

    def test_a_failed_removal_lookup_does_not_let_the_round_advance(self):
        """A removal is reported once.

        Reading a failed lookup as "it moved" finishes the round, advances the
        cursor past the page that carried the removal, and nothing ever asks
        again — the message stays in the store as though it were never
        deleted. So the round has to stop instead.
        """
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        before = self.folder_state().get("delta")

        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/moved-on"})
        self.graph.lookup_status = 500
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)
        self.assertEqual(self.folder_state().get("delta"), before,
                         "the cursor advanced past an unresolved removal")
        # rows() is (source_id, sender, body, deleted_at, body_cleared_at)
        self.assertIsNone(self.rows()[0][3],
                          "a message was tombstoned on a failed lookup")

        # And the next tick, with the service answering, resolves it.
        self.graph.lookup_status = None
        self.graph.still_present = False
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final3"})
        self.assertEqual(self.run_main(), 0)
        self.assertIsNotNone(self.rows()[0][3])

    def test_a_failed_removal_lookup_keeps_the_reason_it_failed(self):
        """The exit code still has to say what went wrong; a credential that
        expired mid-round is not the same operator problem as a timeout."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.graph.queue({"value": [removed("m1")],
                          "@odata.deltaLink": "http://x/final2"})
        self.graph.lookup_status = 401
        self.assertEqual(self.run_main(), ingest_graph.EXIT_CREDENTIAL)

    def test_something_unrecognised_in_the_variable_is_refused(self):
        os.environ["MS_GRAPH_ACCESS_TOKEN"] = "not-a-token"
        self.assertEqual(self.run_main(), ingest_graph.EXIT_CREDENTIAL)


class TestTheExclusionRulesApply(CollectorCase):
    """Applied in `insert_items`, so this collector inherits them — asserted
    by driving it against a rule rather than by reading the call chain."""

    def rule(self, **kinds):
        Path(self.home, "workspace", "exclusions.json").write_text(
            json.dumps(kinds), encoding="utf-8")

    def test_an_excluded_domain_never_reaches_the_store(self):
        self.rule(domains=["agency.example"])
        self.serve([{"value": [message("m1", sender="Recruiter",
                                       address="r@agency.example")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertEqual(self.rows(), [])

    def test_an_excluded_address_never_reaches_the_store(self):
        self.rule(senders=["dana@example.com"])
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertEqual(self.rows(), [])

    def test_everything_else_still_arrives(self):
        self.rule(domains=["agency.example"])
        self.serve([{"value": [message("keep")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertEqual([r[0] for r in self.rows()], ["keep"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
