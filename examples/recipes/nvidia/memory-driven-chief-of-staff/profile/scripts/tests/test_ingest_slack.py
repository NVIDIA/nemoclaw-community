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

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
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
                status = 429 if reply == "RATELIMIT" else 200
                body = b"" if status == 429 else json.dumps(reply).encode()
                self.send_response(status)
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

    def test_a_user_token_is_accepted(self):
        self.assertEqual(ingest_slack.classify_token("xoxp-1-2-3"), "user")

    def test_an_openshell_placeholder_is_accepted(self):
        self.assertEqual(
            ingest_slack.classify_token("openshell:resolve:env:SLACK_USER_TOKEN"),
            "placeholder")

    def test_a_bot_token_is_named_as_a_bot_token(self):
        self.assertEqual(ingest_slack.classify_token("xoxb-1-2-3"), "bot")

    def test_a_rotating_token_is_named_as_rotating(self):
        """`xoxe.xoxp-` also starts with neither `xoxp-` nor `xoxb-`."""
        self.assertEqual(ingest_slack.classify_token("xoxe.xoxp-1-2"), "rotating")

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
        return ingest_slack.main([])

    def test_a_bot_token_exits_as_a_credential_problem(self):
        self.assertEqual(self._run("xoxb-1-2"), ingest_slack.EXIT_CREDENTIAL)

    def test_a_bot_token_costs_no_api_call(self):
        self._run("xoxb-1-2")
        self.assertEqual(self.slack.calls, [],
                         "the collector called Slack with a token it had "
                         "already decided was wrong")

    def test_a_rotating_token_exits_as_a_credential_problem(self):
        self.assertEqual(self._run("xoxe.xoxp-1-2"), ingest_slack.EXIT_CREDENTIAL)

    def test_never_configured_is_a_state_rather_than_a_failure(self):
        """This file existing is what makes the selector run it.

        Most people will have it long before they connect Slack. If that
        counted as a failure the idle gate would never fire again and the model
        would be woken every half hour to be told there is nothing to do.
        """
        os.environ.pop("SLACK_USER_TOKEN", None)
        self.serve(self.working_slack())
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_OK)

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
        os.environ["SLACK_USER_TOKEN"] = "xoxp-test"
        self.serve(self.working_slack())
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_OK)
        self.assertTrue(ingest_slack.capabilities_path().exists())

        os.environ.pop("SLACK_USER_TOKEN", None)
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_CREDENTIAL)


class TestAFetchWritesRowsTheNormalizerMade(CollectorCase):
    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxp-test"

    def test_a_direct_message_becomes_a_direct_row(self):
        self.serve(self.working_slack())
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_OK)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "D01:1787000000.0001")
        self.assertEqual(rows[0][1], "direct")

    def test_the_sender_is_resolved_to_a_name(self):
        self.serve(self.working_slack())
        ingest_slack.main([])
        self.assertEqual(self.rows()[0][2], "dana")

    def test_the_users_own_messages_are_not_collected(self):
        """A message you sent is not a message you received."""
        self.serve(self.working_slack(history={
            "ok": True, "has_more": False,
            "messages": [message("1787000000.0001", user=USER)]}))
        ingest_slack.main([])
        self.assertEqual(self.rows(), [])

    def test_the_workspace_member_list_is_never_enumerated(self):
        """`users.list` rate-limits a large workspace; names go one at a time."""
        self.serve(self.working_slack())
        ingest_slack.main([])
        self.assertNotIn("users.list", [c[0] for c in self.slack.calls])

    def test_a_second_run_adds_nothing_and_asks_from_the_watermark(self):
        self.serve(self.working_slack())
        ingest_slack.main([])
        self.assertEqual(self.cursors(), {"D01": "1787000000.0001"})
        before = len(self.slack.calls)
        ingest_slack.main([])
        self.assertEqual(len(self.rows()), 1, "the second run duplicated rows")
        asked = [p for m, p in self.slack.calls[before:] if m == "conversations.history"]
        self.assertTrue(asked, "the second run never asked for history")
        self.assertEqual(asked[0].get("oldest"), "1787000000.0001",
                         "the second run re-read from the beginning")


class TestTheCredentialIsNeverEchoed(CollectorCase):
    """The collector may hold a real token on a plain Hermes install."""

    SECRET = "xoxp-9999-DO-NOT-PRINT-THIS"

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
        os.environ["SLACK_USER_TOKEN"] = "xoxp-test"

    def test_a_rejected_token_is_a_credential_failure(self):
        self.serve({"auth.test": {"ok": False, "error": "invalid_auth"}})
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_CREDENTIAL)

    def test_a_rate_limit_has_its_own_code(self):
        self.serve({"auth.test": "RATELIMIT"})
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_RATE_LIMIT)

    def test_an_unreachable_slack_reads_as_a_credential_problem(self):
        """A blocked egress policy and a missing provider look the same here."""
        ingest_slack.API = "http://127.0.0.1:9/api/"
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_CREDENTIAL)

    def test_losing_direct_messages_is_fatal_rather_than_degraded(self):
        """Without `im:history` the recipe is not doing what it claims."""
        self.serve({
            "auth.test": {"ok": True, "user_id": USER, "team_id": "T1"},
            "users.conversations": {"ok": False, "error": "missing_scope"},
        })
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_SCOPE)


class TestAPartlyGrantedAppStillWorks(CollectorCase):
    """An admin can approve an app with less than it asked for.

    Scopes are not a property of the manifest, so the families are probed and
    the ones that came back refused are skipped and reported — not treated as
    an error every half hour.
    """

    def setUp(self):
        super().setUp()
        os.environ["SLACK_USER_TOKEN"] = "xoxp-test"

    def _partial(self):
        def conversations(params):
            if params.get("types") == "im":
                return {"ok": True, "channels": [channel("D01")]}
            if params.get("types") == "mpim":
                return {"ok": True, "channels": []}
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
        self.assertEqual(ingest_slack.main([]), ingest_slack.EXIT_OK)
        self.assertEqual(len(self.rows()), 1)

    def test_the_refused_family_is_reported_rather_than_hidden(self):
        self.serve(self._partial())
        caps = ingest_slack.load_capabilities("xoxp-test")
        self.assertIn("public_channel", caps["missing"])
        self.assertIn("im", caps["available"])

    def test_the_probe_is_cached_so_every_tick_does_not_re_ask(self):
        self.serve(self._partial())
        ingest_slack.main([])
        probes = sum(1 for m, p in self.slack.calls
                     if m == "users.conversations" and p.get("limit") == "1")
        ingest_slack.main([])
        again = sum(1 for m, p in self.slack.calls
                    if m == "users.conversations" and p.get("limit") == "1")
        self.assertEqual(probes, again, "the second tick re-probed the scopes")

    def test_recheck_asks_again(self):
        self.serve(self._partial())
        ingest_slack.main([])
        before = len(self.slack.calls)
        ingest_slack.main(["--recheck"])
        self.assertGreater(len(self.slack.calls), before)

    def test_the_cached_answer_is_not_world_readable(self):
        self.serve(self._partial())
        ingest_slack.main([])
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

    def test_the_manifest_turns_token_rotation_off(self):
        """Enabling it on a Slack app cannot be undone."""
        manifest = json.loads(
            (self.RECIPE / "docs" / "slack_app_manifest.json").read_text())
        self.assertIs(manifest["settings"]["token_rotation_enabled"], False)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
