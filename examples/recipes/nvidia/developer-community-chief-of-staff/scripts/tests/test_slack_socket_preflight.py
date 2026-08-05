# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[1] / "slack_socket_preflight.py"
PROVIDERS_SCRIPT = SCRIPT.parent / "02-providers.sh"
SPEC = importlib.util.spec_from_file_location("slack_socket_preflight", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREFLIGHT
SPEC.loader.exec_module(PREFLIGHT)


def slack_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode()
    return response


def http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=PREFLIGHT.SLACK_CONNECTIONS_URL,
        code=status,
        msg="test error",
        hdrs=None,
        fp=io.BytesIO(b""),
    )


class SlackSocketPreflightTest(TestCase):
    def test_missing_app_token_fails_before_network_call(self) -> None:
        with patch.object(PREFLIGHT.urllib.request, "urlopen") as open_:
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("")
        self.assertEqual(raised.exception.category, "configuration")
        open_.assert_not_called()

    def test_valid_token_and_scope_create_socket_url(self) -> None:
        response = slack_response({"ok": True, "url": "wss://wss-primary.slack.com/link/"})
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response) as open_:
            PREFLIGHT.run_preflight("xapp-test-secret", 4)

        request = open_.call_args.args[0]
        self.assertEqual(request.full_url, PREFLIGHT.SLACK_CONNECTIONS_URL)
        self.assertEqual(request.method, "POST")
        self.assertEqual(open_.call_args.kwargs["timeout"], 4)

    def test_missing_scope_names_connections_write(self) -> None:
        response = slack_response({"ok": False, "error": "missing_scope"})
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xapp-test-secret")
        self.assertEqual(raised.exception.category, "scope")
        self.assertIn("connections:write", str(raised.exception))
        self.assertNotIn("xapp-test-secret", str(raised.exception))

    def test_invalid_token_is_authentication_failure(self) -> None:
        response = slack_response({"ok": False, "error": "invalid_auth"})
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xapp-test-secret")
        self.assertEqual(raised.exception.category, "authentication")

    def test_wrong_token_type_fails_without_network_call(self) -> None:
        with patch.object(PREFLIGHT.urllib.request, "urlopen") as open_:
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xoxb-test-secret")
        self.assertEqual(raised.exception.category, "token-type")
        open_.assert_not_called()

    def test_provider_outage_is_availability_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request,
            "urlopen",
            side_effect=http_error(503),
        ):
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xapp-test-secret")
        self.assertEqual(raised.exception.category, "slack-availability")

    def test_network_timeout_is_bounded(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(socket.timeout()),
        ):
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xapp-test-secret", 3)
        self.assertEqual(raised.exception.category, "timeout")

    def test_invalid_response_is_rejected(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"not-json"
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(PREFLIGHT.SlackPreflightError) as raised:
                PREFLIGHT.run_preflight("xapp-test-secret")
        self.assertEqual(raised.exception.category, "slack-response")


class OutlookOnlyProviderPhaseTest(TestCase):
    def test_outlook_only_setup_does_not_run_slack_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command_log = Path(temp_dir) / "commands.log"
            fake_openshell = Path(temp_dir) / "openshell"
            fake_python = Path(temp_dir) / "python3"
            fake_openshell.write_text(
                """#!/usr/bin/env bash
printf 'openshell %s\\n' "$*" >> "$COMMAND_LOG"
if [[ "$1 $2" == "settings get" ]]; then
  echo "providers_v2_enabled = true"
  exit 0
fi
if [[ "$1 $2" == "provider get" ]]; then
  exit 1
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_python.write_text(
                """#!/usr/bin/env bash
printf 'python3 %s\\n' "$*" >> "$COMMAND_LOG"
if [[ "$1" == *"login-ms-graph.py" ]]; then
  echo '{"refresh_token":"test-refresh","expires_at_ms":4102444800000}'
elif [[ "$*" == *"refresh_token"* ]]; then
  echo 'test-refresh'
else
  echo '4102444800000'
fi
""",
                encoding="utf-8",
            )
            fake_openshell.chmod(0o755)
            fake_python.chmod(0o755)

            environment = {
                **os.environ,
                "PATH": f"{temp_dir}:{os.environ['PATH']}",
                "COMMAND_LOG": str(command_log),
                "OUTLOOK_LOGIN_CACHE": "0",
                "OUTLOOK_TENANT_ID": "test-tenant",
                "OUTLOOK_CLIENT_ID": "test-client",
                "OUTLOOK_TARGET_MAILBOX": "agent@example.test",
                "OUTLOOK_REPLY_TO": "owner@example.test",
                "NEMOCLAW_INFERENCE_PREFLIGHT": "0",
                "ATIF_EXPORT_MODE": "local",
            }
            for name in (
                "SLACK_BOT_TOKEN",
                "SLACK_APP_TOKEN",
                "OPENAI_API_KEY",
                "COMPATIBLE_API_KEY",
                "GITHUB_TOKEN",
            ):
                environment.pop(name, None)

            result = subprocess.run(
                ["bash", str(PROVIDERS_SCRIPT)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            log = command_log.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("slack_socket_preflight.py", log)
