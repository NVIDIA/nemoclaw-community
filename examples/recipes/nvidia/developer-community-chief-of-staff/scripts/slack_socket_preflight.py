#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate a Slack app token and its Socket Mode scope."""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

SLACK_CONNECTIONS_URL = "https://slack.com/api/apps.connections.open"
TOKEN_ENV = "NEMOCLAW_SLACK_PREFLIGHT_TOKEN"
REQUIRED_SCOPE = "connections:write"


@dataclass
class SlackPreflightError(Exception):
    category: str
    detail: str
    exit_code: int

    def __str__(self) -> str:
        return f"Slack Socket Mode preflight failed ({self.category}): {self.detail}"


def classify_slack_error(error: str) -> SlackPreflightError:
    if error == "missing_scope":
        return SlackPreflightError(
            "scope",
            f"app-level token requires the {REQUIRED_SCOPE} scope",
            4,
        )
    if error in {
        "invalid_auth",
        "not_authed",
        "token_expired",
        "token_revoked",
        "account_inactive",
    }:
        return SlackPreflightError(
            "authentication",
            "Slack rejected the app-level token",
            3,
        )
    if error == "not_allowed_token_type":
        return SlackPreflightError(
            "token-type",
            "SLACK_APP_TOKEN must be an app-level xapp- token",
            3,
        )
    if error in {
        "access_denied",
        "forbidden_team",
        "no_permission",
        "ekm_access_denied",
        "enterprise_is_restricted",
    }:
        return SlackPreflightError(
            "workspace-access",
            "workspace policy does not allow this Socket Mode connection",
            5,
        )
    if error in {"fatal_error", "internal_error"}:
        return SlackPreflightError(
            "slack-availability",
            "Slack could not create a Socket Mode connection",
            6,
        )
    return SlackPreflightError(
        "slack-response",
        f"apps.connections.open returned {error or 'an unknown error'}",
        6,
    )


def run_preflight(token: str, timeout: float = 10.0) -> None:
    if not token:
        raise SlackPreflightError("configuration", "SLACK_APP_TOKEN is missing", 2)
    if not token.startswith("xapp-"):
        raise SlackPreflightError(
            "token-type",
            "SLACK_APP_TOKEN must be an app-level xapp- token",
            3,
        )
    if timeout <= 0:
        raise SlackPreflightError(
            "configuration",
            "timeout must be greater than zero",
            2,
        )

    request = urllib.request.Request(
        SLACK_CONNECTIONS_URL,
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(16384))
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise SlackPreflightError(
                "authentication",
                f"Slack rejected the app-level token (HTTP {error.code})",
                3,
            ) from None
        if error.code == 429 or error.code >= 500:
            raise SlackPreflightError(
                "slack-availability",
                f"Slack could not serve the preflight request (HTTP {error.code})",
                6,
            ) from None
        raise SlackPreflightError(
            "slack-response",
            f"unexpected Slack HTTP status {error.code}",
            6,
        ) from None
    except (TimeoutError, socket.timeout):
        raise SlackPreflightError(
            "timeout",
            f"Slack did not respond within {timeout:g} seconds",
            7,
        ) from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise SlackPreflightError(
                "timeout",
                f"Slack did not respond within {timeout:g} seconds",
                7,
            ) from None
        raise SlackPreflightError(
            "connectivity",
            "Slack is unreachable or its TLS certificate is invalid",
            7,
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SlackPreflightError(
            "slack-response",
            "Slack returned an invalid response",
            6,
        ) from None

    if payload.get("ok") is not True:
        raise classify_slack_error(str(payload.get("error", "")))
    if not str(payload.get("url", "")).startswith("wss://"):
        raise SlackPreflightError(
            "slack-response",
            "Slack response did not include a Socket Mode URL",
            6,
        )


def main() -> int:
    try:
        timeout = float(os.environ.get("NEMOCLAW_SLACK_PREFLIGHT_TIMEOUT_SECONDS", "10"))
        run_preflight(os.environ.get(TOKEN_ENV, ""), timeout)
    except (ValueError, SlackPreflightError) as error:
        if isinstance(error, ValueError):
            error = SlackPreflightError(
                "configuration",
                "NEMOCLAW_SLACK_PREFLIGHT_TIMEOUT_SECONDS must be numeric",
                2,
            )
        print(error, file=sys.stderr)
        return error.exit_code

    print(f"Slack Socket Mode preflight passed ({REQUIRED_SCOPE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
