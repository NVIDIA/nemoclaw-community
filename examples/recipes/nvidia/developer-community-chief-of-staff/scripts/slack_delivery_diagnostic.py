#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run a guided, operator-originated Slack delivery diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


EXAMPLE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = EXAMPLE_DIR / ".env"
SANDBOX_SCRIPT = "/usr/local/lib/nemoclaw/slack-delivery-diagnostic.py"
DIAGNOSTIC_LOG = Path("/tmp/nemoclaw-slack-diagnostic.jsonl")
SOCKET_STATUS = Path("/tmp/nemoclaw-slack-socket-status.json")
STAGE_ORDER = (
    "socket_mode_connection",
    "inbound_event_receipt",
    "hermes_dispatch",
    "inference",
    "outbound_response",
)
STAGE_LABELS = {
    "slack_api_access": "Slack API access",
    "socket_mode_connection": "Socket Mode connection",
    "inbound_event_receipt": "inbound event receipt",
    "hermes_dispatch": "Hermes dispatch",
    "inference": "inference",
    "outbound_response": "outbound response",
}
FAILURE_ACTIONS = {
    "missing_inbound_event": (
        "Confirm the app's event subscription or slash command, then check that "
        "Socket Mode remains enabled in Slack."
    ),
    "dispatch_filter": (
        "Confirm that the sending member is in SLACK_ALLOWED_IDS, or leave the "
        "allowlist empty only when workspace-wide access is intended."
    ),
    "inference_timeout": (
        "Check the Hermes gateway and inference route. A busy session can also "
        "delay dispatch until the diagnostic timeout."
    ),
    "inference_failure": (
        "Check the configured inference provider, model, and gateway logs."
    ),
    "outbound_response_timeout": (
        "Check Slack chat:write access, app installation, and outbound policy."
    ),
    "outbound_response_failure": (
        "Check Slack chat:write access, app installation, and outbound policy."
    ),
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def authorization_description(raw: str) -> str:
    member_count = len([item for item in raw.split(",") if item.strip()])
    if member_count:
        noun = "member" if member_count == 1 else "members"
        return f"explicit allowlist ({member_count} {noun})"
    return "allow-all (no SLACK_ALLOWED_IDS value)"


def slack_api_access(token: str, timeout: float = 10.0) -> tuple[bool, str]:
    if not token:
        return False, "SLACK_BOT_TOKEN is missing from .env"
    if not token.startswith("xoxb-"):
        return False, "SLACK_BOT_TOKEN must be a bot access token"

    request = urllib.request.Request(
        "https://slack.com/api/auth.test",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(16384))
    except (TimeoutError, socket.timeout):
        return False, f"Slack API did not respond within {timeout:g} seconds"
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            return False, "Slack rejected the bot access token"
        return False, f"Slack API returned HTTP {error.code}"
    except urllib.error.URLError:
        return False, "Slack API is unreachable or its TLS certificate is invalid"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, "Slack API returned an invalid response"

    if not isinstance(payload, dict):
        return False, "Slack API returned an invalid response"
    if payload.get("ok") is not True:
        error = str(payload.get("error") or "unknown_error")
        if error in {"invalid_auth", "not_authed", "token_expired", "token_revoked"}:
            return False, "Slack rejected the bot access token"
        return False, f"Slack auth.test failed ({error})"
    return True, ""


def read_events(path: Path = DIAGNOSTIC_LOG) -> list[dict[str, Any]]:
    try:
        if path.is_symlink() or not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    events: list[dict[str, Any]] = []
    for line in lines[-5000:]:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def read_socket_status(path: Path = SOCKET_STATUS) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return event if isinstance(event, dict) else None


def _pid_is_running(raw_pid: Any) -> bool:
    try:
        pid = int(raw_pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def socket_connection_status(events: list[dict[str, Any]]) -> dict[str, Any]:
    connection_events = [
        event
        for event in events
        if event.get("stage") == "socket_mode_connection"
        and not event.get("diagnostic_id")
    ]
    if not connection_events:
        return {
            "ok": False,
            "last_stage": "slack_api_access",
            "category": "missing_instrumentation",
        }
    latest = max(
        connection_events,
        key=lambda event: float(event.get("timestamp") or 0),
    )
    connected = latest.get("status") == "confirmed" and _pid_is_running(
        latest.get("pid")
    )
    return {
        "ok": connected,
        "last_stage": (
            "socket_mode_connection" if connected else "slack_api_access"
        ),
        "category": "" if connected else "socket_mode_connection_failure",
    }


def evaluate_delivery(
    events: list[dict[str, Any]],
    *,
    timed_out: bool,
    now: float | None = None,
    failure_settle_seconds: float = 2.0,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        if stage in STAGE_ORDER[1:]:
            latest[stage] = event

    confirmed = [
        stage
        for stage in STAGE_ORDER[1:]
        if latest.get(stage, {}).get("status") == "confirmed"
    ]
    last_stage = "socket_mode_connection"
    for stage in STAGE_ORDER[1:]:
        if stage in confirmed:
            last_stage = stage

    inference = latest.get("inference", {})
    outbound = latest.get("outbound_response", {})
    if inference.get("status") == "failed":
        return {
            "ok": False,
            "pending": False,
            "category": "inference_failure",
            "last_stage": "hermes_dispatch",
            "confirmed": confirmed,
        }
    if (
        inference.get("status") == "confirmed"
        and outbound.get("status") == "confirmed"
    ):
        return {
            "ok": True,
            "pending": False,
            "category": "",
            "last_stage": "outbound_response",
            "confirmed": confirmed,
        }
    if (
        inference.get("status") == "confirmed"
        and outbound.get("status") == "failed"
    ):
        failure_age = now - float(outbound.get("timestamp") or now)
        if timed_out or failure_age >= failure_settle_seconds:
            return {
                "ok": False,
                "pending": False,
                "category": "outbound_response_failure",
                "last_stage": "inference",
                "confirmed": confirmed,
            }
    if not timed_out:
        return {
            "ok": False,
            "pending": True,
            "category": "",
            "last_stage": last_stage,
            "confirmed": confirmed,
        }

    inbound = latest.get("inbound_event_receipt", {})
    dispatch = latest.get("hermes_dispatch", {})
    if inbound.get("status") != "confirmed":
        category = "missing_inbound_event"
        last_stage = "socket_mode_connection"
    elif dispatch.get("status") != "confirmed":
        category = "dispatch_filter"
        last_stage = "inbound_event_receipt"
    elif inference.get("status") != "confirmed":
        category = "inference_timeout"
        last_stage = "hermes_dispatch"
    else:
        category = "outbound_response_timeout"
        last_stage = "inference"
    return {
        "ok": False,
        "pending": False,
        "category": category,
        "last_stage": last_stage,
        "confirmed": confirmed,
    }


def watch_delivery(test_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matching = [
            event
            for event in read_events()
            if event.get("diagnostic_id") == test_id
        ]
        result = evaluate_delivery(matching, timed_out=False)
        if not result["pending"]:
            return result
        time.sleep(0.25)
    matching = [
        event
        for event in read_events()
        if event.get("diagnostic_id") == test_id
    ]
    return evaluate_delivery(matching, timed_out=True)


def _parse_helper_json(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def run_sandbox_helper(
    sandbox: str,
    arguments: list[str],
    timeout: float,
) -> dict[str, Any] | None:
    command = [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        sandbox,
        "--",
        "python3",
        SANDBOX_SCRIPT,
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_helper_json(result.stdout)


def _print_confirmed(stage: str) -> None:
    print(f"[confirmed] {STAGE_LABELS[stage]}", flush=True)


def run_operator_diagnostic(args: argparse.Namespace) -> int:
    env = read_env(ENV_FILE)
    token = env.get("SLACK_BOT_TOKEN", "")
    api_ok, api_error = slack_api_access(token, args.api_timeout)
    if not api_ok:
        print(f"[failed] Slack API access: {api_error}", file=sys.stderr)
        return 2
    _print_confirmed("slack_api_access")

    status = run_sandbox_helper(args.sandbox, ["--sandbox-status"], 15)
    if not status:
        print(
            "[failed] Could not read diagnostic instrumentation from the sandbox. "
            "Rebuild the sandbox with this version of the recipe.",
            file=sys.stderr,
        )
        return 3
    if not status.get("ok"):
        print(
            "[failed] Last confirmed stage: Slack API access. "
            "Check the Hermes gateway and Socket Mode connection.",
            file=sys.stderr,
        )
        return 4
    _print_confirmed("socket_mode_connection")

    test_id = f"NC-{secrets.token_hex(4).upper()}"
    auth_mode = authorization_description(env.get("SLACK_ALLOWED_IDS", ""))
    print(f"Authorization mode: {auth_mode}")
    if args.mode == "dm":
        print("Send this direct message to the bot:")
        print(f"  NemoClaw delivery diagnostic {test_id}. Reply with the same code.")
    else:
        print("Run this configured slash command in Slack:")
        print(
            f"  {args.slash_command} NemoClaw delivery diagnostic {test_id}. "
            "Reply with the same code."
        )
    print(f"Waiting up to {args.timeout:g} seconds...", flush=True)

    result = run_sandbox_helper(
        args.sandbox,
        ["--sandbox-watch", test_id, "--timeout", str(args.timeout)],
        args.timeout + 15,
    )
    if not result:
        print(
            "[failed] The bounded sandbox diagnostic did not return a result.",
            file=sys.stderr,
        )
        return 5

    for stage in STAGE_ORDER[1:]:
        if stage in result.get("confirmed", []):
            _print_confirmed(stage)
    if result.get("ok"):
        print("Slack delivery diagnostic passed.")
        return 0

    category = str(result.get("category") or "inference_timeout")
    last_stage = str(result.get("last_stage") or "socket_mode_connection")
    action = FAILURE_ACTIONS.get(category, "Check the Hermes gateway logs.")
    print(
        f"[failed] Last confirmed stage: {STAGE_LABELS.get(last_stage, last_stage)}. "
        f"{action}",
        file=sys.stderr,
    )
    return 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trace an operator-originated Slack message through Hermes",
    )
    parser.add_argument("--mode", choices=("dm", "slash"), default="dm")
    parser.add_argument(
        "--slash-command",
        help="Configured Slack command, for example /alice-nemoclaw",
    )
    parser.add_argument(
        "--sandbox",
        default=os.environ.get("SANDBOX_NAME", "hermes-direct"),
    )
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--api-timeout", type=float, default=10.0)
    parser.add_argument("--sandbox-status", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sandbox-watch", metavar="ID", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (
        not math.isfinite(args.timeout)
        or not math.isfinite(args.api_timeout)
        or args.timeout <= 0
        or args.api_timeout <= 0
    ):
        parser.error("timeouts must be finite and greater than zero")

    if args.sandbox_status:
        events = read_events()
        socket_status = read_socket_status()
        if socket_status:
            events.append(socket_status)
        result = socket_connection_status(events)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.sandbox_watch:
        if not re.fullmatch(r"NC-[A-F0-9]{8}", args.sandbox_watch):
            parser.error("invalid diagnostic ID")
        result = watch_delivery(args.sandbox_watch, args.timeout)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1

    if args.mode == "slash":
        if not args.slash_command:
            parser.error("--slash-command is required for --mode slash")
        if not re.fullmatch(r"/[a-z0-9][a-z0-9-]{0,31}", args.slash_command):
            parser.error("--slash-command must be lowercase and hyphen-separated")
    return run_operator_diagnostic(args)


if __name__ == "__main__":
    raise SystemExit(main())
