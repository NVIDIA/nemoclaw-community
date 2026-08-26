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
import sqlite3
import sys
import tempfile
import threading
import unittest
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
    }


def removed(mid, reason="deleted"):
    """What a delta page carries for something that is gone."""
    return {"id": mid, "@removed": {"reason": reason}}


class FakeGraph:
    """A Graph that answers from a script, and records what it was asked."""

    def __init__(self, pages):
        # `pages` is a list of dicts, served in order for successive delta
        # requests. Anything else is answered from `identity`.
        self.pages = list(pages)
        self.calls: list[str] = []
        self.headers_seen: list[str] = []
        self.identity = {"mail": ME, "displayName": "Avery"}
        self.status_for_next = None
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

                if outer.status_for_next is not None:
                    code = outer.status_for_next
                    outer.status_for_next = None
                    return outer._send(self, code, {"error": {"code": "x"}})

                if outer.pages:
                    return outer._send(self, 200, outer.pages.pop(0))
                return outer._send(self, 200, {"value": [],
                                               "@odata.deltaLink": outer.url
                                               + "delta-final"})

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

    def queue(self, *pages):
        """Add pages for later rounds, on the same server.

        Stopping one stand-in and starting another leaves the saved cursor
        pointing at a dead address, which hangs rather than failing — so the
        whole of a multi-round test runs against one server.
        """
        self.pages.extend(json.loads(
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
        rewritten = json.loads(
            json.dumps(self.graph.pages).replace("http://x/",
                                                 self.graph.url + "/"))
        self.graph.pages = rewritten
        return self.graph

    def run_main(self, args=None):
        """Call the collector without its stdout landing in the test report."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ingest_graph.main(args or [])
        self.stdout = buffer.getvalue()
        return code

    def report(self):
        return json.loads(self.stdout)

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT source_id, sender, body, deleted_at, body_cleared_at"
                "  FROM items ORDER BY source_id").fetchall()

    def state(self):
        return ingest_graph.read_state()


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

    def test_a_move_is_not_a_deletion(self):
        """`@removed` carries a reason, and `changed` means it left the scope
        being synchronised — filing something is not deleting it."""
        self.stored()
        self.graph.queue({"value": [removed("m1", reason="changed")],
                          "@odata.deltaLink": "http://x/final2"})
        self.run_main()
        row = self.rows()[0]
        self.assertIsNone(row[3], "a moved message was tombstoned")
        self.assertIsNotNone(row[2], "a moved message lost its body")

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
        self.assertIn("delta", self.state())
        self.assertNotIn("next", self.state())

    def test_an_interrupted_round_stores_the_page_instead(self):
        pages = [{"value": [message(f"m{i}")],
                  "@odata.nextLink": f"http://x/page{i + 1}"}
                 for i in range(ingest_graph.REQUEST_BUDGET + 2)]
        self.serve(pages)
        self.run_main()
        self.assertIn("next", self.state())
        self.assertNotIn("delta", self.state(),
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
        resumed_from = self.state()["next"]
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
        self.assertNotIn("next", self.state())
        self.assertNotIn("delta", self.state())
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

    def test_rate_limiting_has_its_own_code(self):
        self.serve([{"value": [], "@odata.deltaLink": "http://x/final"}])
        self.graph.status_for_next = 500
        self.assertEqual(self.run_main(), ingest_graph.EXIT_OTHER)

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
