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
        # requests. Anything else is answered from `identity`.
        self.pages = list(pages)
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
                    hits = [{"id": "elsewhere"}] if outer.still_present else []
                    return outer._send(self, 200, {"value": hits})

                if outer.rate_limit_forever:
                    body = json.dumps({"error": {"code": "throttled"}}).encode()
                    self.send_response(429)
                    self.send_header("Retry-After", "1")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

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
        first_cursor = self.state()["delta"]
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

    def test_a_changed_mailbox_forgets_the_old_message_identities(self):
        """They answer "moved or deleted" for messages in a mailbox nobody is
        reading any more."""
        self.serve([{"value": [message("m1")],
                     "@odata.deltaLink": "http://x/final"}])
        self.run_main()
        self.assertTrue(self.state().get("message_ids"))

        self.graph.identity = {"mail": "someone.else@example.com"}
        self.graph.queue({"value": [], "@odata.deltaLink": "http://x/f2"})
        self.run_main()
        self.assertNotIn("m1", self.state().get("message_ids", {}))

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
        first = self.state()["delta"]
        self.graph.queue({"value": [], "@odata.deltaLink": "http://x/final"})
        self.run_main()
        self.assertEqual(self.state()["delta"], first)


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

    def test_the_throttling_bound_is_a_total_not_a_per_wait(self):
        """Each individual wait was already bounded; the sum was not."""
        self.assertLessEqual(ingest_graph.MAX_BACKOFF_SECONDS,
                             ingest_graph.MAX_TOTAL_BACKOFF_SECONDS)

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
