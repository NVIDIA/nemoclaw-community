#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Detect Slack response failures and request bounded host-side recovery."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

EXAMPLE_DIR = Path(os.environ.get("EXAMPLE_DIR", Path(__file__).resolve().parents[2]))
ENV_FILE = EXAMPLE_DIR / ".env"
STATE_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "nemoclaw-autoheal/response-monitor.json"
WATCHDOG = Path(__file__).with_name("watchdog.sh")
LOG_PREFIX = "[nemoclaw-response-monitor]"


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", file=sys.stderr, flush=True)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def split_allowed_ids(raw: str) -> tuple[list[str], list[str]]:
    users: list[str] = []
    channels: list[str] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if item.startswith(("U", "W")):
            users.append(item)
        elif item.startswith(("D", "C", "G")):
            channels.append(item)
    return users, channels


def classify_log_text(text: str) -> set[str]:
    lower = text.lower()
    failures: set[str] = set()
    if any(marker in lower for marker in ("http 503", "http 504", "gateway time-out", "inference service unavailable")):
        failures.add("inference_proxy")
    if any(marker in lower for marker in ("serverdisconnectederror", "server disconnected", "slackapierror")):
        failures.add("slack_gateway")
    graph_net_failure = re.search(r"net:fail.*graph\.microsoft\.com:443|graph\.microsoft\.com:443.*net:fail", lower)
    if graph_net_failure or any(marker in lower for marker in ("remote end closed connection without response", "microsoft graph api")):
        failures.add("outlook_graph")
    return failures


def should_remediate(last_action: float, now: float, cooldown_secs: int) -> bool:
    return now - last_action >= cooldown_secs


def slack_api(token: str, method: str, params: dict[str, Any] | None = None, post: bool = False) -> dict[str, Any]:
    params = params or {}
    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if post:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(params).encode()
    elif params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if post else "GET")
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode())


def run(command: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2))
    temporary.replace(STATE_FILE)


def resolve_channels(token: str, allowed_users: list[str], explicit_channels: list[str]) -> list[str]:
    channels = list(dict.fromkeys(explicit_channels))
    for user_id in allowed_users:
        try:
            response = slack_api(token, "users.conversations", {"user": user_id, "types": "im", "limit": 20})
            if not response.get("ok"):
                response = slack_api(token, "conversations.open", {"users": user_id}, post=True)
                channel_id = (response.get("channel") or {}).get("id")
                if channel_id:
                    channels.append(channel_id)
                continue
            channels.extend(channel["id"] for channel in response.get("channels", []) if channel.get("id"))
        except Exception as exc:  # Network/API failure is itself a recovery signal.
            log(f"could not resolve Slack DM: {exc.__class__.__name__}")
    return list(dict.fromkeys(channels))


def is_bot_message(message: dict[str, Any], bot_user_id: str, bot_id: str | None) -> bool:
    return message.get("user") == bot_user_id or (bot_id is not None and message.get("bot_id") == bot_id)


def latest_unanswered(token: str, channel_id: str, bot_user_id: str, bot_id: str | None, allowed_users: set[str], window_secs: int, grace_secs: int) -> str | None:
    response = slack_api(token, "conversations.history", {"channel": channel_id, "limit": 30, "oldest": str(time.time() - window_secs), "inclusive": "true"})
    if not response.get("ok"):
        log(f"history unavailable for {channel_id}: {response.get('error', 'unknown')}")
        return None
    messages = sorted(response.get("messages", []), key=lambda item: float(item.get("ts", "0")), reverse=True)
    now = time.time()
    for index, message in enumerate(messages):
        sender = message.get("user")
        if message.get("type") != "message" or message.get("subtype") or not sender or sender == bot_user_id:
            continue
        if allowed_users and sender not in allowed_users:
            continue
        if now - float(message.get("ts", "0")) < grace_secs:
            return None
        newer = messages[:index]
        if not any(is_bot_message(candidate, bot_user_id, bot_id) for candidate in newer):
            return f"{channel_id}:{message.get('ts')}"
        return None
    return None


def recent_gateway_failures() -> set[str]:
    sandbox = os.environ.get("SANDBOX_NAME", "hermes-direct")
    command = [
        "bash", "-lc",
        "container=$(docker ps --format '{{.Names}}' | grep '^openshell-" + sandbox + "' | head -n1); "
        "[ -n \"$container\" ] && docker logs --since=15m --tail=5000 \"$container\" 2>&1",
    ]
    _, output = run(command, timeout=12)
    return classify_log_text(output)


def remediate(reason: str, dry_run: bool) -> None:
    log(f"recovery requested: {reason}")
    if not dry_run:
        subprocess.run(["bash", str(WATCHDOG)], check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--window-secs", type=int, default=int(os.environ.get("NEMOCLAW_SLACK_MONITOR_WINDOW_SECS", "900")))
    parser.add_argument("--grace-secs", type=int, default=int(os.environ.get("NEMOCLAW_SLACK_MONITOR_GRACE_SECS", "90")))
    parser.add_argument("--cooldown-secs", type=int, default=int(os.environ.get("NEMOCLAW_SLACK_MONITOR_COOLDOWN_SECS", "300")))
    args = parser.parse_args()

    env = read_env(ENV_FILE)
    state = load_state()
    now = time.time()
    failures = recent_gateway_failures()

    token = env.get("SLACK_BOT_TOKEN", "")
    if token:
        try:
            auth = slack_api(token, "auth.test")
            if not auth.get("ok"):
                failures.add("slack_auth")
            else:
                users, channels = split_allowed_ids(env.get("SLACK_ALLOWED_IDS", ""))
                for channel_id in resolve_channels(token, users, channels):
                    unanswered = latest_unanswered(token, channel_id, auth["user_id"], auth.get("bot_id"), set(users), args.window_secs, args.grace_secs)
                    if unanswered:
                        failures.add("unanswered_slack_message")
                        state["last_unanswered_key"] = unanswered
                        break
        except Exception as exc:
            log(f"Slack API check failed: {exc.__class__.__name__}")
            failures.add("slack_api")

    if not failures:
        log("ok: no response or transport failures detected")
        return 0

    last_action = float(state.get("last_action_time", 0))
    if not should_remediate(last_action, now, args.cooldown_secs):
        log("recovery cooldown is active")
        return 0
    remediate(",".join(sorted(failures)), args.dry_run)
    if not args.dry_run:
        state["last_action_time"] = now
        save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
