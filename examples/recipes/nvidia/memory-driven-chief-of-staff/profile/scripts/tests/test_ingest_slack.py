# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Slack collector, against a stand-in Slack.

These run the real module against a local HTTP server that answers like the
Slack API, rather than matching patterns in the source. The difference matters:
the defects this collector can have — a watermark that does not advance, a
token echoed into a log, an error mapped to the wrong exit code — are all
invisible to a test that only reads the file.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import ingest_slack  # noqa: E402

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")

USER = "U0AVERY001"
OTHER = "U0DANA0001"


class FakeSlack:
    """A Slack that answers from a script, and records what it was asked."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.headers_seen: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: A003
                pass

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                method = parsed.path.rsplit("/", 1)[-1]
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                outer.calls.append((method, params))
                outer.headers_seen.append(self.headers.get("Authorization", ""))
                reply = outer.responses.get(method, {"ok": False, "error": "unknown_method"})
                if callable(reply):
                    reply = reply(params)
                headers = {}
                if reply == "RETRY_AFTER":
                    headers["Retry-After"] = "1"
                status = 429 if reply in ("RATELIMIT", "RETRY_AFTER") else 200
                body = b"" if status == 429 else json.dumps(reply).encode()
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/"

    def stop(self):
        self.server.shutdown()


def channel(cid, family="im"):
    flags = {"id": cid}
    if family == "im":
        flags["is_im"] = True
    elif family == "mpim":
        flags["is_mpim"] = True
    return flags


def message(ts, user=OTHER, text="hello"):
    return {"ts": ts, "user": user, "text": text}


class CollectorCase(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        env = patch.dict(os.environ, {"INTAKE_GRAPH_SENT_ITEMS": "0", "INTAKE_SLACK_SELF_AUTHORED": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.home = tempfile.mkdtemp()
        Path(self.home, "workspace", "ledger").mkdir(parents=True)
        self.db = Path(self.home) / "workspace" / "ledger" / "state.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
        os.environ["HERMES_HOME"] = self.home
        self.slack = None
        self._api = ingest_slack.API

    def tearDown(self):
        if self.slack:
            self.slack.stop()
        ingest_slack.API = self._api
        os.environ.pop("SLACK_USER_TOKEN", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def serve(self, responses):
        self.slack = FakeSlack(responses)
        ingest_slack.API = self.slack.url
        return self.slack

    def run_main(self, args=None):
        """Call the collector without its stdout landing in the test report.

        The README tells the reader every test file ends with `OK`. A module
        that prints its result to stdout while under test puts a line after
        that one, and the documented expectation stops being true — which is
        the same class of drift these tests exist to catch.
        """
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ingest_slack.main(args or [])
        self.stdout = buffer.getvalue()
        return code

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT source_id, addressing, sender FROM items ORDER BY source_id"
            ).fetchall()

    def cursors(self):
        with sqlite3.connect(self.db) as conn:
            return dict(conn.execute(
                "SELECT scope, cursor FROM cursors WHERE source='slack'").fetchall())

    def working_slack(self, history=None):
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]} if p.get("types") == "im"
                else {"ok": True, "channels": []}),
            "conversations.history": history or {
                "ok": True, "has_more": False,
                "messages": [message("1787000000.0001")]},
            "users.info": {"ok": True, "user": {"real_name": "Dana Ruiz",
                                                "profile": {"display_name": "dana"}}},
        }


class TestTheTokenIsClassifiedBeforeItIsSpent(unittest.TestCase):
    """A bot token does not fail — it succeeds at seeing nothing.

    That is the failure this recipe most has to prevent, because it looks
    exactly like a quiet week. Naming the prefix costs one comparison and turns
    a silent wrong answer into a sentence telling the reader which token to
    copy instead.
    """

    def test_a_rotating_user_token_is_what_this_recipe_wants(self):
        self.assertEqual(ingest_slack.classify_token("xoxe.xoxp-1-2-3"), "rotating")

    def test_a_non_rotating_user_token_is_named_static(self):
        """It works, and is refused anyway — it never expires."""
        self.assertEqual(ingest_slack.classify_token("xoxp-1-2-3"), "static")

    def test_an_openshell_placeholder_is_accepted(self):
        self.assertEqual(
            ingest_slack.classify_token("openshell:resolve:env:SLACK_USER_TOKEN"),
            "placeholder")

    def test_a_bot_token_is_named_as_a_bot_token(self):
        self.assertEqual(ingest_slack.classify_token("xoxb-1-2-3"), "bot")

    def test_an_app_token_is_named_as_an_app_token(self):
        self.assertEqual(ingest_slack.classify_token("xapp-1-2"), "app")

    def test_absent_and_blank_are_the_same_thing(self):
        for value in (None, "", "   "):
            self.assertEqual(ingest_slack.classify_token(value), "absent")

    def test_the_bot_explanation_says_which_token_to_copy_instead(self):
        text = ingest_slack._explain("bot")
        self.assertIn("xoxp-", text)
        self.assertIn("direct messages", text)


class TestTheWrongTokenNeverReachesSlack(CollectorCase):
    """Refusing has to happen before the call, not after it fails."""

    def _run(self, token):
        os.environ["SLACK_USER_TOKEN"] = token
        self.serve(self.working_slack())
        return self.run_main()

    def test_a_bot_token_exits_as_a_credential_problem(self):
        self.assertEqual(self._run("xoxb-1-2"), ingest_slack.EXIT_CREDENTIAL)

    def test_a_bot_token_costs_no_api_call(self):
        self._run("xoxb-1-2")
        self.assertEqual(self.slack.calls, [],
                         "the collector called Slack with a token it had "
                         "already decided was wrong")

    def test_a_static_token_exits_as_a_credential_problem(self):
        """A token that never expires is a permanent key to one person's Slack."""
        self.assertEqual(self._run("xoxp-1-2"), ingest_slack.EXIT_CREDENTIAL)

    def test_the_static_explanation_says_why_rather_than_only_no(self):
        text = ingest_slack._explain("static")
        self.assertIn("never expires", text)
        self.assertIn("rotation", text)

    def test_never_configured_is_a_state_rather_than_a_failure(self):
        """This file existing is what makes the selector run it.

        Most people will have it long before they connect Slack. If that
        counted as a failure the idle gate would never fire again and the model
        would be woken every half hour to be told there is nothing to do.
        """
        os.environ.pop("SLACK_USER_TOKEN", None)
        self.serve(self.working_slack())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)

    def test_never_configured_says_so_on_stdout(self):
        os.environ.pop("SLACK_USER_TOKEN", None)
        self.serve(self.working_slack())
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\nimport ingest_slack\n"
             "raise SystemExit(ingest_slack.main([]))" % str(HERE)],
            capture_output=True, text=True,
            env={k: v for k, v in os.environ.items() if k != "SLACK_USER_TOKEN"})
        self.assertEqual(json.loads(proc.stdout), {"unconfigured": True})

    def test_a_credential_that_disappears_is_a_failure(self):
        """A detached provider empties the variable too.

        Without this the two cases are indistinguishable and a connector that
        was working yesterday goes quiet instead of loud — the exact failure
        the wake gate exists to prevent.
        """
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.serve(self.working_slack())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)
        self.assertTrue(ingest_slack.capabilities_path().exists())

        os.environ.pop("SLACK_USER_TOKEN", None)
        self.assertEqual(self.run_main(), ingest_slack.EXIT_CREDENTIAL)


class TestAFetchWritesRowsTheNormalizerMade(CollectorCase):
    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def test_a_direct_message_becomes_a_direct_row(self):
        self.serve(self.working_slack())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "D01:1787000000.0001")
        self.assertEqual(rows[0][1], "direct")

    def test_the_sender_is_resolved_to_a_name(self):
        self.serve(self.working_slack())
        self.run_main()
        self.assertEqual(self.rows()[0][2], "dana")

    def test_the_users_own_messages_are_not_collected(self):
        """A message you sent is not a message you received."""
        self.serve(self.working_slack(history={
            "ok": True, "has_more": False,
            "messages": [message("1787000000.0001", user=USER)]}))
        self.run_main()
        self.assertEqual(self.rows(), [])

    def test_the_workspace_member_list_is_never_enumerated(self):
        """`users.list` rate-limits a large workspace; names go one at a time."""
        self.serve(self.working_slack())
        self.run_main()
        self.assertNotIn("users.list", [c[0] for c in self.slack.calls])

    def test_a_second_run_adds_nothing_and_asks_from_the_watermark(self):
        self.serve(self.working_slack())
        self.run_main()
        self.assertEqual(self.cursors(), {"D01": "1787000000.0001"})
        before = len(self.slack.calls)
        self.run_main()
        self.assertEqual(len(self.rows()), 1, "the second run duplicated rows")
        asked = [p for m, p in self.slack.calls[before:] if m == "conversations.history"]
        self.assertTrue(asked, "the second run never asked for history")
        self.assertEqual(asked[0].get("oldest"), "1787000000.0001",
                         "the second run re-read from the beginning")


class TestTheCredentialIsNeverEchoed(CollectorCase):
    """The collector may hold a real token on a plain Hermes install."""

    SECRET = "xoxe.xoxp-9999-DO-NOT-PRINT-THIS"

    def test_no_stream_contains_the_token_on_success(self):
        os.environ["SLACK_USER_TOKEN"] = self.SECRET
        self.serve(self.working_slack())
        proc = self._subprocess()
        self.assertNotIn("DO-NOT-PRINT-THIS", proc.stdout)
        self.assertNotIn("DO-NOT-PRINT-THIS", proc.stderr)

    def test_no_stream_contains_the_token_when_slack_rejects_it(self):
        os.environ["SLACK_USER_TOKEN"] = self.SECRET
        self.serve({"auth.test": {"ok": False, "error": "invalid_auth"}})
        proc = self._subprocess()
        self.assertNotIn("DO-NOT-PRINT-THIS", proc.stdout)
        self.assertNotIn("DO-NOT-PRINT-THIS", proc.stderr)
        self.assertEqual(proc.returncode, ingest_slack.EXIT_CREDENTIAL)

    def test_the_token_did_travel_in_the_header(self):
        """Proving absence from the logs is only worth it if it was in use."""
        os.environ["SLACK_USER_TOKEN"] = self.SECRET
        self.serve(self.working_slack())
        self._subprocess()
        self.assertTrue(any(self.SECRET in h for h in self.slack.headers_seen),
                        "the token never reached the Authorization header")

    def _subprocess(self):
        env = {**os.environ, "HERMES_HOME": self.home,
               "SLACK_API_BASE_FOR_TEST": self.slack.url}
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "import os, ingest_slack\n"
            "ingest_slack.API = os.environ['SLACK_API_BASE_FOR_TEST']\n"
            "raise SystemExit(ingest_slack.main([]))\n" % str(HERE)
        )
        return subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, env=env)


class TestFailuresCarryTheirDiagnosisInTheExitCode(CollectorCase):
    """The selector drops a collector's text, so the code has to mean something."""

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def test_a_rejected_token_is_a_credential_failure(self):
        self.serve({"auth.test": {"ok": False, "error": "invalid_auth"}})
        self.assertEqual(self.run_main(), ingest_slack.EXIT_CREDENTIAL)

    def test_a_rate_limit_has_its_own_code(self):
        self.serve({"auth.test": "RATELIMIT"})
        self.assertEqual(self.run_main(), ingest_slack.EXIT_RATE_LIMIT)

    def test_an_unreachable_slack_reads_as_a_credential_problem(self):
        """A blocked egress policy and a missing provider look the same here."""
        ingest_slack.API = "http://127.0.0.1:9/api/"
        self.assertEqual(self.run_main(), ingest_slack.EXIT_CREDENTIAL)

    def test_losing_direct_messages_is_fatal_rather_than_degraded(self):
        """Without `im:history` the recipe is not doing what it claims."""
        self.serve({
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": {"ok": False, "error": "missing_scope"},
        })
        self.assertEqual(self.run_main(), ingest_slack.EXIT_SCOPE)


class TestAPartlyGrantedAppStillWorks(CollectorCase):
    """An admin can approve an app with less than it asked for.

    Scopes are not a property of the manifest, so the families are probed and
    the ones that came back refused are skipped and reported — not treated as
    an error every half hour.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _partial(self):
        def conversations(params):
            if params.get("types") == "im":
                return {"ok": True, "channels": [channel("D01")]}
            return {"ok": False, "error": "missing_scope"}
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": conversations,
            "conversations.history": {"ok": True, "has_more": False,
                                      "messages": [message("1787000000.0001")]},
            "users.info": {"ok": True, "user": {"real_name": "Dana",
                                                "profile": {}}},
        }

    def test_the_run_succeeds_on_the_families_that_were_granted(self):
        self.serve(self._partial())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)
        self.assertEqual(len(self.rows()), 1)

    def test_the_refused_family_is_reported_rather_than_hidden(self):
        """`mpim`, not `public_channel`: the latter is skipped when unnamed."""
        self.serve(self._partial())
        caps = ingest_slack.load_capabilities("xoxe.xoxp-test")
        self.assertIn("mpim", caps["missing"])
        self.assertIn("im", caps["available"])

    def test_an_unnamed_public_channel_family_is_neither_available_nor_missing(self):
        """Nothing to read is not the same as being refused permission."""
        self.serve(self._partial())
        caps = ingest_slack.load_capabilities("xoxe.xoxp-test")
        self.assertNotIn("public_channel", caps["available"])
        self.assertNotIn("public_channel", caps["missing"])

    def test_the_probe_is_cached_so_every_tick_does_not_re_ask(self):
        self.serve(self._partial())
        self.run_main()
        probes = sum(1 for m, p in self.slack.calls
                     if m == "users.conversations" and p.get("limit") == "1")
        self.run_main()
        again = sum(1 for m, p in self.slack.calls
                    if m == "users.conversations" and p.get("limit") == "1")
        self.assertEqual(probes, again, "the second tick re-probed the scopes")

    def test_recheck_asks_again(self):
        self.serve(self._partial())
        self.run_main()
        before = len(self.slack.calls)
        self.run_main(["--recheck"])
        self.assertGreater(len(self.slack.calls), before)

    def test_the_cached_answer_is_not_world_readable(self):
        self.serve(self._partial())
        self.run_main()
        path = Path(self.home) / "workspace" / "slack_capabilities.json"
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o077, 0,
                         "the capability cache is readable by other users")


class TestPrivateChannelsAreLeftOutOnPurpose(unittest.TestCase):
    """Documented as a deliberate omission, so it gets an assertion.

    `groups:*` commonly needs admin approval, and a manifest asking for a scope
    the admin refuses can cost the whole install rather than that one scope.
    """

    RECIPE = HERE.parents[1]

    def test_the_manifest_asks_for_no_private_channel_scope(self):
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        user = manifest["oauth_config"]["scopes"]["user"]
        for scope in ("groups:read", "groups:history"):
            self.assertNotIn(scope, user)

    def test_the_manifest_asks_for_no_bot_scope_at_all(self):
        """No bot token means no bot token to paste by mistake."""
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        self.assertEqual(manifest["oauth_config"]["scopes"]["bot"], [])

    def test_the_manifest_turns_token_rotation_on(self):
        """The gateway is what keeps the credential short-lived.

        Enabling rotation on a Slack app cannot be undone, so this is a real
        commitment rather than a default — and it is the commitment the
        approved design makes: a user token that never expires is a permanent
        key to one person's entire Slack.
        """
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        self.assertIs(manifest["settings"]["token_rotation_enabled"], True)

    def test_the_manifest_declares_a_redirect_url(self):
        """Rotation requires the OAuth flow, and the flow requires a redirect.

        Slack refuses to create the app without one, which is how this was
        found — the first manifest omitted it and could not be imported.
        """
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        self.assertTrue(manifest["oauth_config"].get("redirect_urls"))

    def test_the_collector_reads_no_private_channels(self):
        self.assertNotIn("private_channel", ingest_slack.FAMILIES)

    def test_every_scope_the_collector_probes_is_in_the_manifest(self):
        """The manifest and the code have to ask for the same thing."""
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        user = set(manifest["oauth_config"]["scopes"]["user"])
        for family, scope in ingest_slack.FAMILIES.items():
            self.assertIn(scope, user,
                          f"the collector reads {family} but the manifest "
                          f"never asks for {scope}")


class TestAnIncompleteCrawlDoesNotMoveTheWatermark(CollectorCase):
    """`has_more` with no cursor to follow used to commit anyway.

    `conversations.history` pages from newest backwards, so a crawl that stops
    early holds the newest messages and is missing older ones — and the gap
    sits above the watermark, where `oldest=` will never look again. Advancing
    the cursor there loses those messages permanently, on a run that exits
    zero and reports success.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _truncated(self):
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]} if p.get("types") == "im"
                else {"ok": True, "channels": []}),
            "conversations.history": lambda p: (
                {"ok": True, "messages": [message("1787000009.0001")],
                 "has_more": True, "response_metadata": {}}
                if p.get("limit") != "1" else {"ok": True, "messages": []}),
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_the_cursor_stays_put(self):
        self.serve(self._truncated())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)
        self.assertEqual(self.cursors(), {},
                         "a truncated crawl advanced the watermark past "
                         "messages it never fetched")

    def test_the_rows_it_did_get_are_still_kept(self):
        """Not advancing must not mean discarding."""
        self.serve(self._truncated())
        self.run_main()
        self.assertEqual(len(self.rows()), 1)

    def test_the_run_says_the_crawl_was_incomplete(self):
        self.serve(self._truncated())
        self.run_main()
        payload = json.loads(self.stdout)
        self.assertIn("incomplete_coverage", payload)
        self.assertIn("im", payload["incomplete_coverage"]["truncated_families"])


class TestOneBadConversationDoesNotDiscardTheRest(CollectorCase):
    """A single rate-limited channel used to roll the whole run back.

    Zero rows, zero cursors, and the next tick enumerating the same channels in
    the same order to reproduce it exactly — a livelock that wakes the model
    every half hour to redo work it will throw away.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _three_with_one_broken(self, broken="D02"):
        def history(params):
            if params.get("limit") == "1":
                return {"ok": True, "messages": []}
            if params.get("channel") == broken:
                return {"ok": False, "error": "ratelimited"}
            return {"ok": True, "has_more": False,
                    "messages": [message("1787000000.0001")]}
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01"), channel("D02"),
                                          channel("D03")]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": history,
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_the_healthy_conversations_are_still_stored(self):
        self.serve(self._three_with_one_broken())
        self.run_main()
        stored = {row[0].split(":")[0] for row in self.rows()}
        self.assertEqual(stored, {"D01", "D03"},
                         "a failure in one conversation discarded the others")

    def test_their_watermarks_advanced(self):
        """Progress has to be monotonic, or the next tick repeats the run."""
        self.serve(self._three_with_one_broken())
        self.run_main()
        self.assertEqual(set(self.cursors()), {"D01", "D03"})

    def test_the_failure_is_reported_without_naming_the_conversation(self):
        """A DM id names who the user talks to, and this becomes a prompt."""
        self.serve(self._three_with_one_broken())
        self.run_main()
        payload = json.loads(self.stdout)
        # The property is that nothing names the conversation, not that the
        # report has one exact shape — a thread-level failure carries a
        # `scope` and is equally anonymous.
        self.assertTrue(payload["partial"], "the failure was not reported")
        for entry in payload["partial"]:
            self.assertEqual(entry["family"], "im")
            self.assertIn("error", entry)
            self.assertNotIn("D02", json.dumps(entry))
        self.assertNotIn("D02", self.stdout)

    def test_a_partial_failure_still_exits_zero(self):
        self.serve(self._three_with_one_broken())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)

    def test_every_conversation_failing_is_a_failed_run(self):
        def history(params):
            if params.get("limit") == "1":
                return {"ok": True, "messages": []}
            return {"ok": False, "error": "ratelimited"}
        responses = self._three_with_one_broken()
        responses["conversations.history"] = history
        self.serve(responses)
        self.assertEqual(self.run_main(), ingest_slack.EXIT_RATE_LIMIT)


class TestTheFirstRunIsBounded(CollectorCase):
    """No lower bound meant draining a channel's entire history in one tick.

    On a real account that is tens of thousands of requests, which rate-limits,
    which throws the run away, which starts from the top again — a first run
    that can never finish. A time window bounds it while keeping every crawl
    complete, which a page cap would not.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def test_the_first_fetch_asks_for_a_window_not_everything(self):
        self.serve(self.working_slack())
        self.run_main()
        fetches = [p for m, p in self.slack.calls
                   if m == "conversations.history" and p.get("limit") != "1"]
        self.assertTrue(fetches)
        self.assertIn("oldest", fetches[0],
                      "the first run asked for a channel's whole history")
        age = time.time() - float(fetches[0]["oldest"])
        self.assertLess(abs(age - ingest_slack.BACKFILL_DAYS * 86400), 600)

    def test_a_later_run_uses_the_watermark_not_the_window(self):
        self.serve(self.working_slack())
        self.run_main()
        before = len(self.slack.calls)
        self.run_main()
        fetches = [p for m, p in self.slack.calls[before:]
                   if m == "conversations.history" and p.get("limit") != "1"]
        self.assertEqual(fetches[0]["oldest"], "1787000000.0001")


class TestOnlyPeopleTalkingCount(CollectorCase):
    """Joins, leaves, topic changes and bot posts are not messages to the user.

    In a DM they all arrive as `direct`, this recipe's highest-priority class,
    and a bot message carries no `user` field so it also slipped the
    "not my own message" filter and landed with a NULL sender.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _noisy(self):
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]} if p.get("types") == "im"
                else {"ok": True, "channels": []}),
            "conversations.history": lambda p: (
                {"ok": True, "messages": []} if p.get("limit") == "1" else
                {"ok": True, "has_more": False, "messages": [
                    {"ts": "1787000000.0001", "user": OTHER,
                     "subtype": "channel_join", "text": "has joined"},
                    {"ts": "1787000000.0002", "bot_id": "B1",
                     "text": "PR #42 opened"},
                    {"ts": "1787000000.0003", "user": OTHER,
                     "subtype": "channel_topic", "text": "set the topic"},
                    {"ts": "1787000000.0004", "user": OTHER,
                     "text": "can you review this by Friday"},
                ]}),
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_only_the_real_message_is_stored(self):
        self.serve(self._noisy())
        self.run_main()
        self.assertEqual([row[0] for row in self.rows()],
                         ["D01:1787000000.0004"])

    def test_a_bot_post_never_arrives_with_a_null_sender(self):
        self.serve(self._noisy())
        self.run_main()
        self.assertTrue(all(row[2] for row in self.rows()),
                        "a row was stored with no sender at all")

    def test_the_watermark_still_passes_the_skipped_ones(self):
        """Skipping must not mean re-reading them forever."""
        self.serve(self._noisy())
        self.run_main()
        self.assertEqual(self.cursors(), {"D01": "1787000000.0004"})


class TestTheProbeChecksTheCallItWillActuallyMake(CollectorCase):
    """`users.conversations` needs `im:read`; the fetch needs `im:history`.

    An install granting the first and withholding the second — the plausible
    split, since history is the sensitive half — passed the old probe and then
    failed on every fetch, producing exit 4 on every tick with no way for
    `--recheck` to clear it, because the probe itself was what was wrong.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def test_read_without_history_is_caught_at_probe_time(self):
        self.serve({
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": {"ok": True, "channels": [channel("D01")]},
            "conversations.history": {"ok": False, "error": "missing_scope"},
        })
        self.assertEqual(self.run_main(), ingest_slack.EXIT_SCOPE)

    def test_the_probe_calls_history_and_not_only_the_listing(self):
        self.serve(self.working_slack())
        self.run_main()
        probes = [p for m, p in self.slack.calls
                  if m == "conversations.history" and p.get("limit") == "1"]
        self.assertTrue(probes, "the probe never tried the call it needs")

    def test_an_empty_family_is_not_invented_into_a_failure(self):
        """Nothing to read means history access cannot be tested, not refused."""
        self.serve({
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": {"ok": True, "channels": []},
        })
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)


class TestReplacingTheTokenReplacesTheIdentity(CollectorCase):
    """The cache holds the `user_id` every message is compared against.

    Left un-invalidated across a token change it identifies the previous owner,
    so the new owner's own outgoing messages are ingested as messages they
    received — and the setup doc tells people to rotate exactly this way.
    """

    def test_a_different_token_re_probes(self):
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-first"
        self.serve(self.working_slack())
        self.run_main()
        first = json.loads(ingest_slack.capabilities_path().read_text())

        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-second"
        self.slack.responses["auth.test"] = {"ok": True, "user_id": "U0NEWME",
                                             "team_id": "T1"}
        self.run_main()
        second = json.loads(ingest_slack.capabilities_path().read_text())
        self.assertEqual(second["user_id"], "U0NEWME",
                         "the cache still identifies the previous owner")
        self.assertNotEqual(first["credential"], second["credential"])

    def test_the_cache_stores_a_fingerprint_and_not_the_token(self):
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-secret-value"
        self.serve(self.working_slack())
        self.run_main()
        raw = ingest_slack.capabilities_path().read_text()
        self.assertNotIn("xoxe.xoxp-secret-value", raw)
        self.assertIn("credential", json.loads(raw))


class TestCoverageIsBoundedAndRotates(CollectorCase):
    """Slack allows one `conversations.history` per minute for affected apps.

    A workspace sweep cannot finish inside a half-hour tick; it spends the
    window being throttled and then throws the work away. So a tick is given a
    request budget, and what it could not reach is reported rather than left
    to look like an absence of messages. The starting point rotates, or the
    same first few conversations would be served forever.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def tearDown(self):
        os.environ.pop("INTAKE_SLACK_BUDGET", None)
        super().tearDown()

    def _many(self, n=6):
        ids = [f"D{i:02d}" for i in range(n)]
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel(c) for c in ids]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": {"ok": True, "has_more": False,
                                      "messages": [message("1787000000.0001")]},
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_a_tick_stops_at_its_budget(self):
        os.environ["INTAKE_SLACK_BUDGET"] = "4"
        self.serve(self._many(6))
        self.run_main()
        payload = json.loads(self.stdout)
        self.assertLess(payload["served"], payload["conversations"])
        self.assertTrue(payload["incomplete_coverage"]["budget_exhausted"])

    def test_what_it_could_not_reach_is_counted(self):
        os.environ["INTAKE_SLACK_BUDGET"] = "4"
        self.serve(self._many(6))
        self.run_main()
        gap = json.loads(self.stdout)["incomplete_coverage"]
        self.assertGreater(gap["conversations_unserved"], 0)

    def test_the_next_tick_starts_where_this_one_stopped(self):
        """Otherwise the tail of the list is never read at all."""
        os.environ["INTAKE_SLACK_BUDGET"] = "3"
        self.serve(self._many(6))
        self.run_main()
        first = {c["channel"] for m, c in self.slack.calls
                 if m == "conversations.history" and c.get("limit") != "1"}
        before = len(self.slack.calls)
        self.run_main()
        second = {c["channel"] for m, c in self.slack.calls[before:]
                  if m == "conversations.history" and c.get("limit") != "1"}
        self.assertTrue(second - first,
                        "the second tick served only conversations the first "
                        "had already covered")

    def test_a_budget_that_would_spend_nothing_is_refused(self):
        for bad in ("0", "-1", "abc"):
            os.environ["INTAKE_SLACK_BUDGET"] = bad
            self.serve(self._many(2))
            with self.assertRaises(SystemExit):
                self.run_main()

    def test_an_unbudgeted_run_still_covers_everything(self):
        """The bound must not become the behaviour when nothing is scarce."""
        self.serve(self._many(3))
        self.run_main()
        payload = json.loads(self.stdout)
        self.assertEqual(payload["served"], payload["conversations"])
        self.assertNotIn("incomplete_coverage", payload)


class TestPublicChannelsAreNamedRatherThanSwept(CollectorCase):
    """`#122` replaces starred discovery with an explicit channel list.

    Reading every channel a person happens to be in collects far more than the
    job needs, and at one request per minute it cannot finish anyway. Direct
    messages need no list — they are the user's by definition.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _responses(self):
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": {"ok": True, "has_more": False,
                                      "messages": [message("1787000000.0001")]},
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_with_no_list_no_public_channel_is_read(self):
        self.serve(self._responses())
        self.run_main()
        read = {c["channel"] for m, c in self.slack.calls
                if m == "conversations.history" and c.get("limit") != "1"}
        self.assertEqual(read, {"D01"})

    def test_a_named_channel_is_read(self):
        path = Path(self.home) / "workspace" / ingest_slack.SCOPE_FILE
        path.write_text(json.dumps({"channels": ["C0TEAM0001"]}))
        self.serve(self._responses())
        self.run_main()
        read = {c["channel"] for m, c in self.slack.calls
                if m == "conversations.history" and c.get("limit") != "1"}
        self.assertIn("C0TEAM0001", read)

    def test_the_workspace_is_never_enumerated_for_channels(self):
        path = Path(self.home) / "workspace" / ingest_slack.SCOPE_FILE
        path.write_text(json.dumps({"channels": ["C0TEAM0001"]}))
        self.serve(self._responses())
        self.run_main()
        asked = [c.get("types") for m, c in self.slack.calls
                 if m == "users.conversations"]
        self.assertNotIn("public_channel", [a for a in asked if a],
                         "the collector listed public channels instead of "
                         "reading the ones it was told about")

    def test_an_unreadable_list_is_treated_as_no_list(self):
        """A broken file must not stop the direct messages being read."""
        path = Path(self.home) / "workspace" / ingest_slack.SCOPE_FILE
        path.write_text("{ not json")
        self.serve(self._responses())
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)


class TestThreadRepliesAreCollected(CollectorCase):
    """`conversations.history` returns parents, not ordinary replies.

    A colleague answering inside a thread in the user's own DM would otherwise
    never become an item — the recipe's central promise failing with no error
    and no log line. `normalize.py` builds `thread_ref` from `thread_ts`, which
    reads as reply support and made the gap easy to miss.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _threaded(self):
        parent = {"ts": "1787000000.0001", "user": OTHER, "text": "kickoff",
                  "reply_count": 2}
        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": lambda p: (
                {"ok": True, "messages": []} if p.get("limit") == "1" else
                {"ok": True, "has_more": False, "messages": [parent]}),
            "conversations.replies": {"ok": True, "messages": [
                parent,
                {"ts": "1787000000.0002", "user": OTHER,
                 "thread_ts": "1787000000.0001",
                 "text": "can you get me the numbers before the review"},
            ]},
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_a_reply_becomes_an_item(self):
        self.serve(self._threaded())
        self.run_main()
        stored = [row[0] for row in self.rows()]
        self.assertIn("D01:1787000000.0002", stored,
                      "a thread reply was never collected")

    def test_the_parent_is_not_stored_twice(self):
        """`conversations.replies` returns the parent alongside its replies."""
        self.serve(self._threaded())
        self.run_main()
        stored = [row[0] for row in self.rows()]
        self.assertEqual(stored.count("D01:1787000000.0001"), 1)

    def test_a_parent_with_no_replies_is_still_checked_later(self):
        """This used to assert the opposite, and the opposite was the defect.

        A parent with no replies was never fetched again, and an ordinary
        thread reply does not appear in `conversations.history` — so once the
        channel watermark passed the parent, its first later reply was
        invisible for as long as the thread stayed alive. Checking costs one
        call, which is why it is bounded rather than avoided.
        """
        responses = self._threaded()
        responses["conversations.history"] = lambda p: (
            {"ok": True, "messages": []} if p.get("limit") == "1" else
            {"ok": True, "has_more": False,
             "messages": [{"ts": "1787000000.0001", "user": OTHER, "text": "hi"}]})
        self.serve(responses)
        self.run_main()
        self.assertIn("conversations.replies",
                      [m for m, _ in self.slack.calls])

    def test_checking_watched_parents_is_bounded_per_tick(self):
        """Otherwise a busy channel spends the whole budget on parents that
        have nothing to say."""
        parents = [{"ts": f"17870000{i:02d}.0001", "user": OTHER,
                    "text": f"m{i}"}
                   for i in range(ingest_slack.THREADS_PER_TICK + 12)]
        responses = self._threaded()
        responses["conversations.history"] = lambda p: (
            {"ok": True, "messages": []} if p.get("limit") == "1" else
            {"ok": True, "has_more": False, "messages": parents})
        os.environ["INTAKE_SLACK_BUDGET"] = "200"
        self.serve(responses)
        self.run_main()
        replies = sum(1 for m, _ in self.slack.calls
                      if m == "conversations.replies")
        self.assertLessEqual(replies, ingest_slack.THREADS_PER_TICK)

    def test_the_next_tick_checks_different_parents(self):
        """Serving the oldest every time never reaches the newest, which are
        the ones most likely to be waiting on a reply.

        The parents here never gain a reply, so they stay in the watched set
        across ticks. That is the case rotation exists for: a parent that
        answers once moves out of the set on its own and would make an
        unrotated collector look fair.
        """
        parents = [{"ts": f"17870000{i:02d}.0001", "user": OTHER,
                    "text": f"m{i}"}
                   for i in range(ingest_slack.THREADS_PER_TICK * 3)]
        responses = self._threaded()
        responses["conversations.history"] = lambda p: (
            {"ok": True, "messages": []} if p.get("limit") == "1" else
            {"ok": True, "has_more": False, "messages": parents})
        # No replies, ever: the parent comes back and nothing else.
        responses["conversations.replies"] = lambda p: (
            {"ok": True, "has_more": False,
             "messages": [{"ts": p.get("ts"), "user": OTHER, "text": "m"}]})
        os.environ["INTAKE_SLACK_BUDGET"] = "200"
        self.serve(responses)
        self.run_main()
        first = {c.get("ts") for m, c in self.slack.calls
                 if m == "conversations.replies"}
        self.slack.calls.clear()
        self.run_main()
        second = {c.get("ts") for m, c in self.slack.calls
                  if m == "conversations.replies"}
        self.assertTrue(first, "the first tick checked nothing")
        self.assertTrue(second - first,
                        "the second tick checked only parents the first "
                        "already had — the newest are never reached")

    def _many_active(self, count):
        """A channel with more threads holding replies than one tick can serve."""
        parents = [{"ts": f"17870000{i:02d}.0001", "user": OTHER,
                    "text": f"m{i}", "reply_count": 2}
                   for i in range(count)]
        responses = self._threaded()
        responses["conversations.history"] = lambda p: (
            {"ok": True, "messages": []} if p.get("limit") == "1" else
            {"ok": True, "has_more": False, "messages": parents})
        responses["conversations.replies"] = lambda p: (
            {"ok": True, "has_more": False,
             "messages": [{"ts": p.get("ts"), "user": OTHER, "text": "parent"},
                          {"ts": p.get("ts") + "1", "user": OTHER,
                           "text": "reply", "thread_ts": p.get("ts")}]})
        return responses

    def served_replies(self):
        return [c.get("ts") for m, c in self.slack.calls
                if m == "conversations.replies"]

    def test_the_next_tick_reaches_different_active_threads(self):
        """Active threads were served oldest-first on every tick, so a channel
        with more of them than the budget covers never reached the newest —
        and those are the ones known to be holding replies."""
        os.environ["INTAKE_SLACK_BUDGET"] = "6"
        self.serve(self._many_active(12))
        self.run_main()
        first = set(self.served_replies())
        self.slack.calls.clear()
        self.run_main()
        second = set(self.served_replies())
        self.assertTrue(first, "the first tick served no thread")
        self.assertTrue(second - first,
                        "the second tick served only threads the first "
                        "already had")

    def test_an_unserved_active_thread_holds_the_channel_watermark(self):
        """Rotation must not become a way to skip replies.

        Rotation changes which active threads a tick serves, not whether the
        rest still count as unread. With more of them than the budget covers,
        the channel must not advance past the ones it did not reach — or the
        next tick starts beyond replies nobody collected.
        """
        os.environ["INTAKE_SLACK_BUDGET"] = "6"
        self.serve(self._many_active(12))
        self.run_main()
        payload = json.loads(self.stdout)
        self.assertIn("incomplete_coverage", payload)
        self.assertEqual(self.cursors(), {},
                         "the channel advanced past threads it had not read")

    def test_active_threads_are_served_before_watched_parents(self):
        """A thread known to hold replies outranks one being checked in case."""
        parents = [{"ts": "1787000001.0001", "user": OTHER, "text": "quiet"},
                   {"ts": "1787000002.0001", "user": OTHER, "text": "busy",
                    "reply_count": 2}]
        responses = self._threaded()
        responses["conversations.history"] = lambda p: (
            {"ok": True, "messages": []} if p.get("limit") == "1" else
            {"ok": True, "has_more": False, "messages": parents})
        os.environ["INTAKE_SLACK_BUDGET"] = "200"
        self.serve(responses)
        self.run_main()
        served = self.served_replies()
        self.assertEqual(served[0], "1787000002.0001",
                         "a watched parent was served before an active thread")

    def test_thread_progress_is_not_recorded_before_the_rows_are_durable(self):
        """A crash between the two skipped those replies permanently.

        `save_threads` writes a file rather than a row, so it cannot share the
        store's transaction — but it can be made to happen strictly after the
        commit. Here the commit is made to fail: the thread watermark must not
        have moved, so the next run reads the same replies again rather than
        starting past messages that were never written.
        """
        self.serve(self._threaded())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        original = ingest_slack.commit_channel

        def refuse(channel, items, watermark):
            raise sqlite3.OperationalError("disk I/O error")

        ingest_slack.commit_channel = refuse
        try:
            with self.assertRaises(sqlite3.Error):
                self.run_main()
        finally:
            ingest_slack.commit_channel = original

        self.assertEqual(
            ingest_slack.read_threads("D01"), {},
            "thread progress was recorded over rows that were never written")

    def test_thread_progress_is_recorded_once_the_rows_are_durable(self):
        """The other half: it must still be recorded on the happy path, or
        every tick re-reads every thread."""
        self.serve(self._threaded())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.run_main()
        self.assertTrue(ingest_slack.read_threads("D01"),
                        "no thread progress recorded after a good run")

    def test_a_failing_thread_does_not_discard_the_conversation(self):
        responses = self._threaded()
        responses["conversations.replies"] = {"ok": False, "error": "ratelimited"}
        self.serve(responses)
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OK)
        self.assertIn("partial", json.loads(self.stdout))


class TestThreadCoverageSurvivesTheWatermark(CollectorCase):
    """A parent's `ts` never changes, so the channel watermark passes it once.

    After that the parent is never returned by `conversations.history` again,
    and a reply arriving later would be invisible for as long as the thread
    stayed alive — a silent gap exactly like the truncated-crawl one, a level
    down. Threads carry their own watermark for that reason.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def _first_then_quiet(self, replies_payload):
        """History returns the parent once; afterwards the channel is quiet."""
        parent = {"ts": "1787000000.0001", "user": OTHER, "text": "kickoff",
                  "reply_count": 1}
        seen = {"history": 0}

        def history(params):
            if params.get("limit") == "1":
                return {"ok": True, "messages": []}
            seen["history"] += 1
            if seen["history"] == 1:
                return {"ok": True, "has_more": False, "messages": [parent]}
            return {"ok": True, "has_more": False, "messages": []}

        return {
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": history,
            "conversations.replies": replies_payload,
            "users.info": {"ok": True, "user": {"real_name": "Dana", "profile": {}}},
        }

    def test_a_reply_arriving_after_the_parent_is_still_found(self):
        parent = {"ts": "1787000000.0001", "user": OTHER, "text": "kickoff"}
        later = {"ts": "1787000900.0009", "user": OTHER,
                 "thread_ts": "1787000000.0001", "text": "numbers before review"}
        state = {"tick": 0}

        def replies(params):
            state["tick"] += 1
            if state["tick"] == 1:
                return {"ok": True, "has_more": False, "messages": [parent]}
            return {"ok": True, "has_more": False, "messages": [parent, later]}

        self.serve(self._first_then_quiet(replies))
        self.run_main()          # parent seen, thread remembered
        self.run_main()          # channel quiet; the thread is re-read anyway
        self.assertIn("D01:1787000900.0009", [row[0] for row in self.rows()],
                      "a reply to an already-watermarked thread was never found")

    def test_a_quiet_tick_still_revisits_known_threads(self):
        self.serve(self._first_then_quiet(
            {"ok": True, "has_more": False, "messages": []}))
        self.run_main()
        before = sum(1 for m, _ in self.slack.calls if m == "conversations.replies")
        self.run_main()
        after = sum(1 for m, _ in self.slack.calls if m == "conversations.replies")
        self.assertGreater(after, before)

    def test_a_truncated_thread_holds_the_channel_watermark_back(self):
        """Advancing past a parent whose replies were cut loses them for good."""
        parent = {"ts": "1787000000.0001", "user": OTHER, "text": "kickoff",
                  "reply_count": 400}
        self.serve({
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": lambda p: (
                {"ok": True, "channels": [channel("D01")]}
                if p.get("types") == "im" else {"ok": True, "channels": []}),
            "conversations.history": lambda p: (
                {"ok": True, "messages": []} if p.get("limit") == "1" else
                {"ok": True, "has_more": False, "messages": [parent]}),
            "conversations.replies": {
                "ok": True, "has_more": True, "response_metadata": {},
                "messages": [parent, {"ts": "1787000000.0002", "user": OTHER,
                                      "thread_ts": "1787000000.0001",
                                      "text": "one of many"}]},
            "users.info": {"ok": True, "user": {"real_name": "D", "profile": {}}},
        })
        self.run_main()
        self.assertEqual(self.cursors(), {},
                         "the channel watermark advanced past a thread whose "
                         "replies were truncated")


class TestTheBudgetCoversEveryCall(CollectorCase):
    """`users.info` counts too — Slack does not exempt it."""

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"

    def tearDown(self):
        os.environ.pop("INTAKE_SLACK_BUDGET", None)
        super().tearDown()

    def test_the_collection_stays_within_its_budget(self):
        """Probe calls are excluded: they run once and are cached afterwards.

        Collection is what recurs every half hour, and it is what the budget
        bounds. `users.info` is inside that bound — Slack does not exempt it,
        and an unbounded name lookup would spend the allowance on decoration.
        """
        os.environ["INTAKE_SLACK_BUDGET"] = "3"
        self.serve(self.working_slack())
        self.run_main()
        spent = sum(1 for m, c in self.slack.calls
                    if m in ("users.conversations", "conversations.history",
                             "users.info") and c.get("limit") != "1")
        self.assertLessEqual(spent, 3,
                             "collection spent more calls than its budget")

    def test_users_info_is_counted_rather_than_free(self):
        os.environ["INTAKE_SLACK_BUDGET"] = "2"
        self.serve(self.working_slack())
        self.run_main()
        names = sum(1 for m, _ in self.slack.calls if m == "users.info")
        collection = sum(1 for m, c in self.slack.calls
                         if m in ("users.conversations", "conversations.history",
                                  "users.info") and c.get("limit") != "1")
        self.assertLessEqual(collection, 2)
        self.assertLessEqual(names, 2)

    def test_a_short_retry_after_reads_as_rate_limiting(self):
        """Not as an unclassified failure, which is what it used to be."""
        self.serve({"auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
                    "users.conversations": "RETRY_AFTER"})
        self.assertEqual(self.run_main(), ingest_slack.EXIT_RATE_LIMIT)


class TestTheCollectorInheritsTheExclusionRules(CollectorCase):
    """The rules are applied in `insert_items`, so the collector gets them free.

    Free is a claim, not a guarantee — the collector could have grown its own
    write path at any point. So this drives the real collector against a real
    rule rather than reading the call chain and concluding it must hold.
    """

    def rule(self, **kinds):
        Path(self.home, "workspace", "exclusions.json").write_text(
            json.dumps(kinds), encoding="utf-8")

    def test_an_excluded_display_name_never_reaches_the_store(self):
        # The collector prefers the Slack display name over the real name, so
        # `dana` is the string a user would actually put in the rule.
        self.rule(senders=["dana"])
        self.serve(self.working_slack())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.rows(), [])

    def test_an_excluded_slack_id_never_reaches_the_store(self):
        """The documented case: a display name is theirs to change, the id is not.

        The collector resolves `U0DANA0001` to `Dana Ruiz` before the row is
        built, so excluding by id only works because the raw id is carried
        alongside for matching.
        """
        self.rule(senders=[OTHER])
        self.serve(self.working_slack())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.rows(), [])

    def test_an_excluded_channel_never_reaches_the_store(self):
        self.rule(channels=["D01"])
        self.serve(self.working_slack())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.rows(), [])

    def test_the_raw_slack_id_is_matched_on_but_never_stored(self):
        """Matching material must not become a new thing the store holds."""
        self.serve(self.working_slack())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.run_main()
        with sqlite3.connect(self.db) as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
            body = conn.execute("SELECT group_concat(sender) FROM items").fetchone()[0]
        self.assertNotIn("sender_id", columns)
        self.assertNotIn(OTHER, body or "")

    def test_everything_not_excluded_still_arrives(self):
        """Otherwise the three tests above would pass on a collector that
        simply stopped writing."""
        self.rule(senders=["Someone Else"])
        self.serve(self.working_slack())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.rows()), 1)


class TestAttachmentsAreNotFetched(CollectorCase):
    """A file-sharing message is kept; the file behind it is not.

    `file_share` is in `KEPT_SUBTYPES`, so the message survives the filter and
    it would be easy to follow `url_private` while doing so.
    """

    def shared_file(self):
        working = self.working_slack()
        working["conversations.history"] = {
            "ok": True, "has_more": False,
            "messages": [{
                "ts": "1787000000.0001", "user": OTHER,
                "subtype": "file_share", "text": "here is the plan",
                "files": [{
                    "id": "F01", "name": "salaries.pdf",
                    "url_private": "https://files.slack.example/salaries.pdf",
                    "url_private_download":
                        "https://files.slack.example/download/salaries.pdf",
                }],
            }]}
        return working

    def test_the_message_is_kept(self):
        self.serve(self.shared_file())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.run_main()
        self.assertEqual(len(self.rows()), 1)

    def test_no_file_endpoint_is_called(self):
        self.serve(self.shared_file())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.run_main()
        called = {method for method, _ in self.slack.calls}
        self.assertEqual({m for m in called if m.startswith("files")}, set())

    def test_nothing_the_file_points_at_is_stored(self):
        """Not the URL either: it is a live handle to the content."""
        self.serve(self.shared_file())
        os.environ["SLACK_USER_TOKEN"] = "xoxe.xoxp-test"
        self.run_main()
        with sqlite3.connect(self.db) as conn:
            everything = "".join(
                str(value) for row in conn.execute("SELECT * FROM items")
                for value in row)
        self.assertNotIn("url_private", everything)
        self.assertNotIn("files.slack.example", everything)
        self.assertNotIn("salaries.pdf", everything)


class TestSelfAuthoredCollection(CollectorCase):
    def setUp(self):
        super().setUp()
        from unittest.mock import patch
        self.now = int(time.time())
        clock = patch.object(ingest_slack.time, "time", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        os.environ["SLACK_USER_TOKEN"] = "openshell:resolve:env:SLACK_USER_TOKEN"
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "1"
        budget = patch.dict(os.environ, {"INTAKE_SLACK_BUDGET": "100"})
        budget.start()
        self.addCleanup(budget.stop)
        Path(self.home, "distribution.yaml").write_text("id: test\n")

    def ts(self, age):
        return f"{self.now - age:.6f}"

    def configured(self, entries, family="im"):
        cid = "D01" if family == "im" else "G01"
        responses = self.working_slack()
        responses["users.conversations"] = lambda p: {
            "ok": True, "channels": [channel(cid, family)] if p.get("types") == family else []}
        responses["conversations.history"] = lambda p: {
            "ok": True, "has_more": False,
            "messages": [m for m in entries if float(m["ts"]) > float(p.get("oldest", 0))]}
        responses["conversations.replies"] = {"ok": True, "has_more": False, "messages": []}
        responses["conversations.info"] = {"ok": True, "channel": {"user": OTHER}}
        responses["users.info"] = lambda p: {"ok": True, "user": {
            "name": "avery" if p["user"] == USER else "dana",
            "profile": {"display_name": "Avery" if p["user"] == USER else "Dana"}}}
        self.serve(responses)
        return entries

    def all_rows(self):
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM items ORDER BY event_at")]

    def state(self, key="slack_outbound_collection"):
        with sqlite3.connect(self.db) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def test_default_off_does_not_collect_self_or_look_up_dm_membership(self):
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "0"
        os.environ["INTAKE_GRAPH_SENT_ITEMS"] = "1"
        self.configured([message(self.ts(1), USER)])
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])
        self.assertFalse(any(method == "conversations.info" for method, _ in self.slack.calls))
        self.assertFalse(json.loads(self.stdout)["self_authored"]["enabled"])

    def test_invalid_flag_stops_before_network_requests(self):
        self.configured([])
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "true"
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OTHER)
        self.assertEqual(self.slack.calls, [])

    def test_dm_preserves_actual_author_and_records_the_other_member(self):
        self.configured([message(self.ts(1), USER, "I will send the report")])
        self.assertEqual(self.run_main(), 0)
        row, = self.all_rows()
        self.assertEqual((row["sender"], row["sender_key"], row["sender_handle"]), ("Avery", USER, "avery"))
        self.assertEqual((row["counterparty_key"], row["counterparty_name"], row["counterparty_basis"]), (OTHER, "Dana", "dm"))
        self.assertEqual(row["source_account"], f"T1:{USER}")
        self.assertEqual(row["direction"], "outbound")
        self.assertIsNone(row["addressing"])

    def test_group_single_mention_excludes_self_and_deduplicates(self):
        self.configured([message(self.ts(1), USER, f"<@{USER}> <@{OTHER}> <@{OTHER}>")], "mpim")
        self.assertEqual(self.run_main(), 0)
        row, = self.all_rows()
        self.assertEqual((row["sender_key"], row["counterparty_key"], row["counterparty_basis"]), (USER, OTHER, "mention"))
        self.assertFalse(any(method == "conversations.info" for method, _ in self.slack.calls))

    def test_group_ambiguous_root_waits_but_an_arbitrary_reply_does_not(self):
        root = message(self.ts(3), USER, f"<@{OTHER}> <@U0THIRD>")
        reply = dict(message(self.ts(2), USER, "Thanks everyone"), thread_ts=root["ts"])
        self.configured([root, reply], "mpim")
        self.assertEqual(self.run_main(), 0)
        first, second = self.all_rows()
        self.assertIsNone(first["counterparty_key"])
        self.assertIsNotNone(first["counterparty_pending_until"])
        self.assertIsNone(second["counterparty_pending_until"])

    def test_group_root_resolves_from_first_reply_without_changing_author(self):
        import outbound
        root = dict(message(self.ts(3), USER, "Any feedback?"), reply_count=1)
        self.configured([root], "mpim")
        self.slack.responses["conversations.replies"] = {"ok": True, "has_more": False,
            "messages": [dict(message(self.ts(1), OTHER), thread_ts=root["ts"])]}
        self.assertEqual(self.run_main(), 0)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(outbound.resolve_pending(conn), 1)
        row = self.all_rows()[0]
        self.assertEqual((row["sender_key"], row["counterparty_key"], row["counterparty_basis"]), (USER, OTHER, "reply"))

    def test_note_to_self_has_no_counterparty_or_pending_resolution(self):
        self.configured([message(self.ts(1), USER)])
        self.slack.responses["conversations.info"] = {"ok": True, "channel": {"user": USER}}
        self.assertEqual(self.run_main(), 0)
        row, = self.all_rows()
        self.assertIsNone(row["counterparty_key"])
        self.assertIsNone(row["counterparty_pending_until"])

    def test_failed_dm_lookup_is_omitted_and_retried_without_cursor_loss(self):
        self.configured([message(self.ts(1), USER)])
        self.slack.responses["conversations.info"] = {"ok": False, "error": "missing_scope"}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])
        self.assertEqual(self.cursors(), {})
        self.assertIsNone(self.state("slack_outbound_done:D01"))
        self.assertEqual(json.loads(self.stdout)["self_authored"]["unresolved_dm_conversations"], 1)
        self.slack.responses["conversations.info"] = {"ok": True, "channel": {"user": OTHER}}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows()[0]["counterparty_key"], OTHER)

    def test_dm_lookup_and_names_share_the_existing_request_budget(self):
        from unittest.mock import patch
        self.configured([message(self.ts(1), USER)])
        ingest_slack.load_capabilities(os.environ["SLACK_USER_TOKEN"])
        self.slack.calls.clear()
        with patch.dict(os.environ, {"INTAKE_SLACK_BUDGET": "3"}):
            self.assertEqual(self.run_main(), 0)
        # auth.test verifies identity outside the collection budget.
        self.assertLessEqual(sum(method != "auth.test" for method, _ in self.slack.calls), 3)
        self.assertEqual(self.all_rows(), [])
        self.assertIn("incomplete_coverage", json.loads(self.stdout))

    def test_person_exclusion_omits_outbound_dm_before_storage(self):
        self.configured([message(self.ts(1), USER, "private outbound fixture")])
        Path(self.home, "workspace", "exclusions.json").write_text(json.dumps({"senders": [OTHER]}))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])
        self.assertNotIn(b"private outbound fixture", self.db.read_bytes())

    def test_unknown_group_membership_does_not_bypass_person_exclusions(self):
        self.configured([message(self.ts(1), USER, f"<@{OTHER}> hello")], "mpim")
        Path(self.home, "workspace", "exclusions.json").write_text(json.dumps({"senders": ["U0THIRD"]}))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])

    def test_channel_exclusion_omits_outbound_even_with_known_recipient(self):
        self.configured([message(self.ts(1), USER)])
        Path(self.home, "workspace", "exclusions.json").write_text(json.dumps({"channels": ["D01"]}))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])

    def test_enabling_after_inbound_cursor_advanced_backfills_only_seven_days(self):
        entries = self.configured([message(self.ts(9 * 86400), USER),
                                   message(self.ts(100), USER), message(self.ts(1), OTHER)])
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "0"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.cursors()["D01"], entries[-1]["ts"])
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "1"
        self.slack.calls.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual({r["source_id"] for r in self.all_rows()}, {f"D01:{m['ts']}" for m in entries[1:]})
        history = [p for m, p in self.slack.calls if m == "conversations.history"]
        self.assertEqual(float(history[0]["oldest"]), self.now - 7 * 86400)
        self.assertEqual(self.cursors()["D01"], entries[-1]["ts"])

    def test_enabling_revisits_an_existing_thread_watermark(self):
        root = dict(message(self.ts(400), OTHER), reply_count=2)
        own = dict(message(self.ts(300), USER), thread_ts=root["ts"])
        last = dict(message(self.ts(200), OTHER), thread_ts=root["ts"])
        self.configured([root])
        self.slack.responses["conversations.replies"] = lambda p: {"ok": True, "has_more": False,
            "messages": [m for m in (own, last) if float(m["ts"]) > float(p.get("oldest", 0))]}
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "0"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(ingest_slack.read_threads("D01")[root["ts"]], last["ts"])
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "1"
        self.assertEqual(self.run_main(), 0)
        self.assertIn(f"D01:{own['ts']}", {r["source_id"] for r in self.all_rows()})

    def test_disabling_preserves_data_and_reenabling_starts_a_new_window(self):
        entries = self.configured([message(self.ts(300), USER)])
        self.assertEqual(self.run_main(), 0)
        first = json.loads(self.state())
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "0"
        entries.append(message(self.ts(200), USER))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.all_rows()), 1)
        os.environ["INTAKE_SLACK_SELF_AUTHORED"] = "1"
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.all_rows()), 2)
        self.assertNotEqual(json.loads(self.state())["generation"], first["generation"])

    def test_incomplete_history_does_not_mark_catchup_complete(self):
        self.configured([message(self.ts(1), USER)])
        self.slack.responses["conversations.history"] = {"ok": True, "has_more": True,
            "messages": [message(self.ts(1), USER)]}
        self.assertEqual(self.run_main(), 0)
        self.assertIsNone(self.state("slack_outbound_done:D01"))
        self.assertEqual(self.cursors(), {})
        self.slack.responses["conversations.history"]["has_more"] = False
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.all_rows()), 1)
        self.assertEqual(self.state("slack_outbound_done:D01"), json.loads(self.state())["generation"])

    def test_thread_reset_failure_keeps_old_file_and_retries(self):
        from unittest.mock import patch
        self.configured([message(self.ts(1), USER)])
        ingest_slack.save_threads("D01", {self.ts(100): self.ts(50)})
        before = ingest_slack.threads_path().read_bytes()
        with patch.object(ingest_slack.os, "replace", side_effect=OSError("fixture failure")):
            self.assertEqual(self.run_main(), ingest_slack.EXIT_OTHER)
        self.assertEqual(ingest_slack.threads_path().read_bytes(), before)
        self.assertIsNone(self.state("slack_outbound_reset:D01"))
        self.assertEqual(self.all_rows(), [])
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.all_rows()), 1)

    def test_row_commit_failure_does_not_complete_catchup_or_skip_own_reply(self):
        from unittest.mock import patch
        root = dict(message(self.ts(300), OTHER), reply_count=1)
        own = dict(message(self.ts(200), USER), thread_ts=root["ts"])
        self.configured([root])
        self.slack.responses["conversations.replies"] = lambda p: {"ok": True, "has_more": False,
            "messages": [own] if float(own["ts"]) > float(p.get("oldest", 0)) else []}
        ingest_slack.save_threads("D01", {root["ts"]: own["ts"]})
        with patch.object(ingest_slack, "commit_channel", side_effect=sqlite3.OperationalError("fixture failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_main()
        self.assertIsNone(self.state("slack_outbound_done:D01"))
        self.assertLess(float(ingest_slack.read_threads("D01")[root["ts"]]), float(own["ts"]))
        self.assertEqual(self.run_main(), 0)
        self.assertIn(f"D01:{own['ts']}", {r["source_id"] for r in self.all_rows()})

    def test_same_placeholder_with_a_different_account_cannot_mix_evidence(self):
        self.configured([message(self.ts(1), USER)])
        self.assertEqual(self.run_main(), 0)
        before = self.all_rows()
        self.slack.responses["auth.test"] = {"ok": True, "user_id": "U0NEWME", "team_id": "T2"}
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OTHER)
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(json.loads(self.state())["account"], f"T1:{USER}")

    def test_malformed_enablement_state_stops_without_advancing_cursors(self):
        self.configured([message(self.ts(1), USER)])
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO meta(key,value) VALUES ('slack_outbound_collection','[]')")
        self.assertEqual(self.run_main(), ingest_slack.EXIT_OTHER)
        self.assertEqual(self.all_rows(), [])
        self.assertEqual(self.cursors(), {})

    def test_live_shaped_collection_feeds_memory_but_own_text_never_becomes_an_ask(self):
        from unittest.mock import patch
        import select_memory
        import select_intake
        self.configured([message(self.ts(2), OTHER, "Can you review this?"),
                         message(self.ts(1), USER, "I will review it")])
        self.assertEqual(self.run_main(), 0)
        with sqlite3.connect(self.db) as conn:
            evidence = select_memory.evidence(conn, "2000-01-01T00:00:00Z")
        self.assertEqual(len(evidence["people"]), 1)
        self.assertTrue(evidence["people"][0]["both_directions"])
        interactions = next(iter(evidence["interactions"].values()))
        self.assertEqual({entry["direction"] for entry in interactions}, {"inbound", "outbound"})
        output = io.StringIO()
        with patch.object(select_intake, "collect", return_value=({}, False)), contextlib.redirect_stdout(output):
            select_intake.main()
        intake = json.loads(output.getvalue().split('{"wakeAgent"')[0])
        self.assertEqual([entry["body"] for entry in intake["slice"]], ["Can you review this?"])

    def test_export_includes_capture_state_and_reset_removes_it_but_keeps_opt_in(self):
        import export_store
        import reset
        self.configured([message(self.ts(1), USER)])
        self.assertEqual(self.run_main(), 0)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "export"
            export_store.export(destination)
            exported = json.loads((destination / "store.json").read_text())
            row, = exported["items"]
            self.assertEqual(row["counterparty_key"], OTHER)
            self.assertIn("slack_outbound_collection", {r["key"] for r in exported["meta"]})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reset.main(["--yes"]), 0)
            self.assertFalse(self.db.exists())
            self.assertFalse(ingest_slack.threads_path().exists())
            self.assertTrue((destination / "store.json").exists())
        self.assertEqual(os.environ["INTAKE_SLACK_SELF_AUTHORED"], "1")

    def test_replay_keeps_legacy_direction_unknown_and_does_not_restore_cleared_body(self):
        self.configured([message(self.ts(1), USER, "must stay cleared")])
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO items(source_id,source,scope,event_at,body_cleared_at) VALUES (?,'slack','D01','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z')", (f"D01:{self.ts(1)}",))
        self.assertEqual(self.run_main(), 0)
        row, = self.all_rows()
        self.assertIsNone(row["direction"])
        self.assertIsNone(row["body"])

    def test_messages_without_human_authorship_are_omitted(self):
        bot = dict(message(self.ts(2), USER), bot_id="BEXAMPLE")
        unknown = message(self.ts(1))
        unknown.pop("user")
        self.configured([bot, unknown])
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.all_rows(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
