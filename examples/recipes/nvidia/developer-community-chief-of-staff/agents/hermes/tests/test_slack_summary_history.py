# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

HERMES_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = HERMES_DIR / "skills/slack-channel-summarizer"
SCRIPT = SKILL_DIR / "scripts/fetch_slack_history.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("fetch_slack_history", SCRIPT)
assert SPEC and SPEC.loader
HISTORY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HISTORY
SPEC.loader.exec_module(HISTORY)


def message(
    timestamp: str,
    text: str,
    *,
    user: str = "U12345678",
    **extra,
):
    return {"ts": timestamp, "text": text, "user": user, **extra}


def permalink(timestamp: str):
    return {
        "ok": True,
        "permalink": f"https://example.slack.com/archives/C12345678/p{timestamp.replace('.', '')}",
    }


class ScriptedApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, token, method, params):
        self.calls.append((token, method, dict(params)))
        if not self.responses:
            raise AssertionError(f"unexpected Slack API call: {method}")
        expected_method, response = self.responses.pop(0)
        if method != expected_method:
            raise AssertionError(f"expected {expected_method}, got {method}")
        return response

    def assert_complete(self, test):
        test.assertEqual([], self.responses)


class SlackSummaryHistoryTest(TestCase):
    def test_cli_uses_real_http_for_history_permalinks_and_threads(self) -> None:
        class SlackHandler(BaseHTTPRequestHandler):
            requests = []

            def log_message(self, _format, *args) -> None:
                pass

            def respond(self, payload) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                query = {
                    key: values[-1]
                    for key, values in urllib.parse.parse_qs(parsed.query).items()
                }
                type(self).requests.append(
                    (parsed.path, query, self.headers.get("Authorization"))
                )

                if parsed.path == "/api/conversations.history":
                    if query.get("cursor") == "history-page-2":
                        self.respond(
                            {
                                "ok": True,
                                "messages": [message("1700000100.000001", "Oldest")],
                                "response_metadata": {"next_cursor": ""},
                            }
                        )
                    else:
                        self.respond(
                            {
                                "ok": True,
                                "messages": [
                                    message("1700000300.000001", "bot", bot_id="B123"),
                                    message(
                                        "1700000200.000001",
                                        "Root",
                                        reply_count=1,
                                        thread_ts="1700000200.000001",
                                    ),
                                ],
                                "response_metadata": {"next_cursor": "history-page-2"},
                            }
                        )
                    return

                if parsed.path == "/api/conversations.replies":
                    self.respond(
                        {
                            "ok": True,
                            "messages": [
                                message(
                                    "1700000200.000001",
                                    "Root",
                                    reply_count=1,
                                    thread_ts="1700000200.000001",
                                ),
                                message(
                                    "1700000210.000001",
                                    "Reply",
                                    user="U22222222",
                                    thread_ts="1700000200.000001",
                                ),
                            ],
                            "response_metadata": {"next_cursor": ""},
                        }
                    )
                    return

                if parsed.path == "/api/chat.getPermalink":
                    self.respond(permalink(query["message_ts"]))
                    return

                self.respond({"ok": False, "error": "unexpected_method"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlackHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        output = io.StringIO()
        arguments = [
            str(SCRIPT),
            "--channel-id",
            "C12345678",
            "--oldest",
            "1700000000",
            "--latest",
            "1700000400",
            "--message-limit",
            "2",
            "--page-cap",
            "3",
            "--replies",
            "--thread-cap",
            "1",
            "--reply-limit",
            "2",
            "--thread-page-cap",
            "2",
        ]
        try:
            with (
                patch.object(
                    HISTORY, "API_BASE", f"http://127.0.0.1:{server.server_port}/api"
                ),
                patch.object(HISTORY, "get_slack_bot_token", return_value="test-token"),
                patch.object(sys, "argv", arguments),
                contextlib.redirect_stdout(output),
            ):
                exit_code = HISTORY.main()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        result = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["coverage"]["pages"])
        self.assertEqual(3, result["coverage"]["inspected_messages"])
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(
            ["Oldest", "Root"], [item["text"] for item in result["messages"]]
        )
        self.assertEqual(
            ["Reply"],
            [item["text"] for item in result["messages"][1]["thread_replies"]],
        )
        self.assertTrue(result["threads"]["complete"])
        self.assertNotIn("test-token", output.getvalue())
        self.assertEqual(
            [
                "/api/conversations.history",
                "/api/conversations.history",
                "/api/chat.getPermalink",
                "/api/chat.getPermalink",
                "/api/conversations.replies",
                "/api/chat.getPermalink",
            ],
            [request[0] for request in SlackHandler.requests],
        )
        self.assertEqual(
            "history-page-2",
            SlackHandler.requests[1][1]["cursor"],
        )
        self.assertEqual(
            {"Bearer test-token"},
            {request[2] for request in SlackHandler.requests},
        )

    def test_paginates_across_filtered_messages_and_applies_time_range(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [
                            message("1700000300.000001", "bot", bot_id="B123"),
                            message("1700000200.000001", "Second"),
                        ],
                        "response_metadata": {"next_cursor": "next-page"},
                    },
                ),
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [message("1700000100.000001", "First")],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
                ("chat.getPermalink", permalink("1700000200.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            oldest="1700000000",
            latest="1700000400",
            message_limit=2,
            page_cap=3,
            api_call=api,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            ["First", "Second"], [item["text"] for item in result["messages"]]
        )
        self.assertEqual(2, result["coverage"]["pages"])
        self.assertEqual(3, result["coverage"]["inspected_messages"])
        self.assertEqual(2, result["coverage"]["human_messages"])
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(
            "1700000000",
            result["coverage"]["requested_range"]["oldest"],
        )
        self.assertEqual(
            "1700000300.000001",
            result["coverage"]["retrieved_range"]["latest"],
        )
        first_params = api.calls[0][2]
        second_params = api.calls[1][2]
        self.assertEqual("1700000000", first_params["oldest"])
        self.assertEqual("1700000400", first_params["latest"])
        self.assertEqual("2", first_params["limit"])
        self.assertEqual("next-page", second_params["cursor"])
        api.assert_complete(self)

    def test_message_limit_reports_truncation(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [
                            message("1700000100.000001", "One"),
                            message("1700000200.000001", "Two"),
                            message("1700000300.000001", "Three"),
                        ],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
                ("chat.getPermalink", permalink("1700000200.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            message_limit=2,
            page_cap=2,
            api_call=api,
        )

        self.assertEqual(2, len(result["messages"]))
        self.assertTrue(result["coverage"]["truncated"])
        self.assertEqual(["message_limit"], result["coverage"]["truncation_reasons"])
        api.assert_complete(self)

    def test_time_pagination_is_used_when_cursor_is_unavailable(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [
                            message("1700000300.000001", "Newest"),
                            message("1700000200.000001", "bot", bot_id="B123"),
                        ],
                        "has_more": True,
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [message("1700000100.000001", "Oldest")],
                        "has_more": False,
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
                ("chat.getPermalink", permalink("1700000300.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            oldest="1700000000",
            latest="1700000400",
            message_limit=3,
            page_cap=3,
            api_call=api,
        )

        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(2, result["coverage"]["pages"])
        self.assertEqual("1700000200.000001", api.calls[1][2]["latest"])
        self.assertEqual("false", api.calls[1][2]["inclusive"])
        self.assertEqual(
            ["Oldest", "Newest"],
            [item["text"] for item in result["messages"]],
        )
        api.assert_complete(self)

    def test_page_cap_reports_incomplete_empty_coverage(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [
                            message("1700000100.000001", "bot", bot_id="B123")
                        ],
                        "response_metadata": {"next_cursor": "more"},
                    },
                )
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            message_limit=2,
            page_cap=1,
            api_call=api,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["empty"])
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(["page_cap"], result["coverage"]["truncation_reasons"])

    def test_workspace_history_limit_reports_incomplete_coverage(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [],
                        "is_limited": True,
                        "response_metadata": {"next_cursor": ""},
                    },
                )
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            api_call=api,
        )

        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(
            ["workspace_history_limit"],
            result["coverage"]["truncation_reasons"],
        )

    def test_empty_history_is_distinct_from_failure(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [],
                        "response_metadata": {"next_cursor": ""},
                    },
                )
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            api_call=api,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["empty"])
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual([], result["messages"])

    def test_slack_failures_are_fail_closed_and_classified(self) -> None:
        cases = [
            ("invalid_auth", {}),
            (
                "missing_scope",
                {"needed": "channels:history", "provided": "channels:read"},
            ),
            ("not_in_channel", {}),
            ("ratelimited", {"retry_after": "30", "http_status": 429}),
            ("internal_error", {}),
        ]
        for error, details in cases:
            with self.subTest(error=error):
                api = ScriptedApi(
                    [
                        (
                            "conversations.history",
                            {"ok": False, "error": error, **details},
                        )
                    ]
                )
                result = HISTORY.collect_channel_history(
                    "token-placeholder",
                    "C12345678",
                    api_call=api,
                )
                self.assertFalse(result["ok"])
                self.assertEqual("history", result["stage"])
                expected_error = "rate_limited" if error == "ratelimited" else error
                self.assertEqual(expected_error, result["error"])
                self.assertNotIn("messages", result)
                self.assertNotIn("token-placeholder", repr(result))

    def test_transport_errors_return_sanitized_failure(self) -> None:
        for transport_error in (
            TimeoutError("private timeout detail"),
            OSError("private transport detail"),
        ):
            with (
                self.subTest(error=transport_error.__class__.__name__),
                patch.object(
                    HISTORY.urllib.request,
                    "urlopen",
                    side_effect=transport_error,
                ),
            ):
                result = HISTORY.collect_channel_history(
                    "token-placeholder",
                    "C12345678",
                )

            self.assertEqual(
                {
                    "ok": False,
                    "channel_id": "C12345678",
                    "stage": "history",
                    "error": "network_error",
                },
                result,
            )
            self.assertNotIn("token-placeholder", repr(result))
            self.assertNotIn(str(transport_error), repr(result))

    def test_malformed_history_message_returns_sanitized_failure(self) -> None:
        malformed_value = "private malformed message"
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [malformed_value],
                        "response_metadata": {"next_cursor": ""},
                    },
                )
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            api_call=api,
        )

        self.assertEqual(
            {
                "ok": False,
                "channel_id": "C12345678",
                "stage": "history",
                "error": "invalid_messages",
            },
            result,
        )
        self.assertNotIn("token-placeholder", repr(result))
        self.assertNotIn(malformed_value, repr(result))
        api.assert_complete(self)

    def test_thread_replies_paginate_and_keep_root_relationship(self) -> None:
        root = message(
            "1700000100.000001",
            "Root",
            reply_count=3,
            thread_ts="1700000100.000001",
        )
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [root],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
                (
                    "conversations.replies",
                    {
                        "ok": True,
                        "messages": [
                            root,
                            message("1700000110.000001", "bot", bot_id="B123"),
                            message("1700000120.000001", "Reply one", user="U22222222"),
                        ],
                        "response_metadata": {"next_cursor": "reply-page"},
                    },
                ),
                (
                    "conversations.replies",
                    {
                        "ok": True,
                        "messages": [
                            message("1700000130.000001", "Reply two", user="U33333333")
                        ],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000120.000001")),
                ("chat.getPermalink", permalink("1700000130.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            include_replies=True,
            reply_limit=2,
            thread_page_cap=3,
            api_call=api,
        )

        replies = result["messages"][0]["thread_replies"]
        self.assertEqual(["Reply one", "Reply two"], [item["text"] for item in replies])
        self.assertEqual(
            ["1700000100.000001", "1700000100.000001"],
            [item["thread_root_ts"] for item in replies],
        )
        self.assertEqual(2, result["threads"]["items"][0]["pages"])
        self.assertEqual(3, result["threads"]["items"][0]["inspected_messages"])
        self.assertTrue(result["threads"]["complete"])
        api.assert_complete(self)

    def test_thread_cap_is_reported(self) -> None:
        first = message("1700000100.000001", "First root", reply_count=1)
        second = message("1700000200.000001", "Second root", reply_count=1)
        reply = message("1700000110.000001", "Reply")
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [first, second],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
                ("chat.getPermalink", permalink("1700000200.000001")),
                (
                    "conversations.replies",
                    {
                        "ok": True,
                        "messages": [first, reply],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000110.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            include_replies=True,
            thread_cap=1,
            api_call=api,
        )

        self.assertEqual(2, result["threads"]["roots_available"])
        self.assertEqual(1, result["threads"]["roots_expanded"])
        self.assertTrue(result["threads"]["truncated"])
        self.assertIn("thread_cap", result["threads"]["truncation_reasons"])
        self.assertNotIn("thread_replies", result["messages"][1])

    def test_permalink_failure_is_fail_closed(self) -> None:
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [message("1700000100.000001", "Evidence")],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", {"ok": False, "error": "missing_scope"}),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            api_call=api,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("permalink", result["stage"])
        self.assertEqual("missing_scope", result["error"])
        self.assertNotIn("messages", result)

    def test_message_text_truncation_is_explicit(self) -> None:
        long_text = "x" * (HISTORY.MAX_TEXT_CHARS + 1)
        api = ScriptedApi(
            [
                (
                    "conversations.history",
                    {
                        "ok": True,
                        "messages": [message("1700000100.000001", long_text)],
                        "response_metadata": {"next_cursor": ""},
                    },
                ),
                ("chat.getPermalink", permalink("1700000100.000001")),
            ]
        )

        result = HISTORY.collect_channel_history(
            "token-placeholder",
            "C12345678",
            api_call=api,
        )

        rendered = result["messages"][0]
        self.assertEqual(HISTORY.MAX_TEXT_CHARS, len(rendered["text"]))
        self.assertTrue(rendered["text_truncated"])

    def test_citation_format_uses_timestamp_user_and_permalink(self) -> None:
        citation = HISTORY.citation_for(
            "0",
            "U12345678",
            "https://example.slack.com/archives/C12345678/p0",
        )
        self.assertEqual(
            "[1970-01-01 00:00 UTC — U12345678]"
            "(https://example.slack.com/archives/C12345678/p0)",
            citation,
        )

    def test_time_boundaries_accept_slack_and_iso_formats(self) -> None:
        self.assertEqual("1700000000", HISTORY.normalize_time_boundary("1700000000"))
        self.assertEqual(
            "1700000000.25", HISTORY.normalize_time_boundary("1700000000.250000")
        )
        self.assertEqual("0", HISTORY.normalize_time_boundary("1970-01-01T00:00:00Z"))

    def test_skill_requires_coverage_and_source_citations(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("fetch_slack_history.py", skill)
        self.assertIn("Copy the `citation` value", skill)
        self.assertIn("Do not summarize when `ok` is `false`", skill)
        self.assertIn("coverage.complete", skill)
        self.assertIn("threads.complete", skill)


if __name__ == "__main__":
    import unittest

    unittest.main()
