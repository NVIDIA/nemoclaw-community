#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
describe_slack_channel.py

Infer what a Slack channel is for, using layered signals from cheap to
expensive:

  1. Channel name tokens (with abbreviation expansion)
  2. Topic and purpose fields
  3. Pinned messages
  4. Bookmarks
  5. Recent human message content (sampled, bot-filtered)
  6. Top human contributors

Outputs a JSON object with a `signals` dict that the caller (Claude) uses
to synthesize a natural-language description. The script does NOT generate
the description itself — that synthesis belongs in the agent layer where
output formatting can change without redeploying the script.

Usage:
    /usr/bin/python3 describe_slack_channel.py --channel-id C0ABCDE1234
    /usr/bin/python3 describe_slack_channel.py --channel-id C0ABCDE1234 --no-history
    /usr/bin/python3 describe_slack_channel.py --channel-id C0ABCDE1234 --history-limit 100
    /usr/bin/python3 describe_slack_channel.py --channel-id C0ABCDE1234 --replies
    /usr/bin/python3 describe_slack_channel.py --channel-id C0ABCDE1234 --resolve-users

Environment:
    SLACK_BOT_TOKEN must be set. The bot must be a member of private
    channels for any history/pin/bookmark calls to succeed there.

Exit codes:
    0  ok
    1  bad arguments or environment
    2  Slack API error that prevented signal collection
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError




SLACK_API_BASE = "https://slack.com/api"
DEFAULT_HISTORY_LIMIT = 50
DEFAULT_TIMEOUT_SECONDS = 15
TOPIC_STALE_DAYS = 365

# Common engineering-org abbreviations. Tune for your workspace.
TOKEN_EXPANSIONS = {
    "eng": "engineering",
    "infra": "infrastructure",
    "ops": "operations",
    "sre": "site reliability",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "k8s": "kubernetes",
    "qa": "quality assurance",
    "ux": "user experience",
    "ui": "user interface",
    "perf": "performance",
    "sec": "security",
    "infosec": "information security",
    "fe": "frontend",
    "be": "backend",
    "db": "database",
    "obs": "observability",
    "rel": "release",
    "dep": "deployment",
    "deps": "dependencies",
    "biz": "business",
    "proj": "project",
    "xfn": "cross functional",
    "inf": "inference",
}


def slack_get(method: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    """Call a Slack Web API GET method and return parsed JSON. Retries on 429."""
    url = f"{SLACK_API_BASE}/{method}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                retry_after = min(int(e.headers.get("Retry-After", "1")), 5)
                time.sleep(retry_after)
                continue
            return {"ok": False, "error": f"http_{e.code}", "detail": str(e)}
        except URLError as e:
            return {"ok": False, "error": "url_error", "detail": str(e)}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": "bad_json", "detail": str(e)}
    return {"ok": False, "error": "rate_limited"}


def tokenize_channel_name(name: str) -> list[str]:
    """Split a channel name on common delimiters, expand known abbreviations."""
    if not name:
        return []
    raw = re.split(r"[-_./]+", name.lower())
    expanded: list[str] = []
    for tok in raw:
        if not tok:
            continue
        expanded.append(TOKEN_EXPANSIONS.get(tok, tok))
    return expanded


def get_channel_info(channel_id: str, token: str) -> dict[str, Any]:
    return slack_get(
        "conversations.info",
        {"channel": channel_id, "include_num_members": "true"},
        token,
    )


def get_pinned_messages(channel_id: str, token: str) -> list[dict[str, Any]]:
    """Return pinned messages (text + author + ts)."""
    resp = slack_get("pins.list", {"channel": channel_id}, token)
    if not resp.get("ok"):
        return []
    pins: list[dict[str, Any]] = []
    for item in resp.get("items", []):
        msg = item.get("message") or {}
        text = msg.get("text") or ""
        if not text:
            continue
        pins.append(
            {
                "text": text[:500],
                "user": msg.get("user"),
                "ts": msg.get("ts"),
            }
        )
    return pins


def get_bookmarks(channel_id: str, token: str) -> list[dict[str, Any]]:
    """Return channel bookmarks (title + link)."""
    resp = slack_get("bookmarks.list", {"channel_id": channel_id}, token)
    if not resp.get("ok"):
        return []
    bookmarks: list[dict[str, Any]] = []
    for bm in resp.get("bookmarks", []):
        bookmarks.append(
            {
                "title": bm.get("title", ""),
                "link": bm.get("link", ""),
            }
        )
    return bookmarks


def resolve_user_ids(
    user_ids: list[str], token: str
) -> dict[str, str]:
    """Return a dict of {user_id: display_name} for the given IDs."""
    resolved: dict[str, str] = {}
    for uid in user_ids:
        resp = slack_get("users.info", {"user": uid}, token)
        if not resp.get("ok"):
            resolved[uid] = uid
            continue
        user = resp.get("user", {})
        profile = user.get("profile") or {}
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or user.get("name")
            or uid
        )
        resolved[uid] = name
    return resolved


def get_thread_replies(
    channel_id: str, ts: str, token: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Fetch the first `limit` replies for a thread (excluding the root message)."""
    resp = slack_get(
        "conversations.replies",
        {"channel": channel_id, "ts": ts, "limit": str(limit + 1)},
        token,
    )
    if not resp.get("ok"):
        return []
    messages = resp.get("messages", [])
    # First message is the root; return only actual replies
    replies: list[dict[str, Any]] = []
    for msg in messages[1:]:
        text = msg.get("text") or ""
        if not text.strip():
            continue
        replies.append({
            "user": msg.get("user") or msg.get("bot_id", ""),
            "is_bot": bool(msg.get("bot_id")),
            "text": text[:500],
            "ts": msg.get("ts"),
        })
    return replies


def get_recent_human_messages(
    channel_id: str, token: str, limit: int
) -> list[dict[str, Any]]:
    """
    Pull recent messages and filter to human content.

    Excludes:
      - bot messages (bot_id present, or subtype == 'bot_message')
      - channel join/leave/topic-change subtypes
      - tombstoned/empty messages
    """
    resp = slack_get(
        "conversations.history",
        {"channel": channel_id, "limit": str(limit)},
        token,
    )
    if not resp.get("ok"):
        return []

    skip_subtypes = {
        "bot_message",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "tombstone",
    }

    human_messages: list[dict[str, Any]] = []
    for msg in resp.get("messages", []):
        if msg.get("bot_id"):
            continue
        if msg.get("subtype") in skip_subtypes:
            continue
        text = msg.get("text") or ""
        if not text.strip():
            continue
        human_messages.append(
            {
                "user": msg.get("user"),
                "text": text[:1000],
                "ts": msg.get("ts"),
                "thread_ts": msg.get("thread_ts"),
                "reply_count": msg.get("reply_count", 0),
            }
        )
    return human_messages


def top_contributors(
    messages: list[dict[str, Any]], n: int = 5
) -> list[dict[str, Any]]:
    """Return top-N user IDs by message count in the sample."""
    counts = Counter(m["user"] for m in messages if m.get("user"))
    return [
        {"user_id": user_id, "message_count": count}
        for user_id, count in counts.most_common(n)
    ]


def is_topic_stale(topic_last_set: int | None, days: int = TOPIC_STALE_DAYS) -> bool:
    """Topic counts as stale if older than `days` or never set."""
    if not topic_last_set:
        return True
    age_seconds = time.time() - int(topic_last_set)
    return age_seconds > days * 86400


def build_result(
    channel_id: str,
    info: dict[str, Any],
    pins: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    user_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the structured result for the caller."""
    channel = info.get("channel", {}) if info.get("ok") else {}
    name = channel.get("name", "")
    topic = (channel.get("topic") or {}).get("value", "")
    topic_last_set = (channel.get("topic") or {}).get("last_set")
    purpose = (channel.get("purpose") or {}).get("value", "")
    is_archived = channel.get("is_archived", False)
    is_private = channel.get("is_private", False)
    num_members = channel.get("num_members")

    contributors_raw = top_contributors(messages) if messages else []
    # Enrich contributors with display names if a user_map was supplied
    contributors: list[dict[str, Any]] = []
    for c in contributors_raw:
        uid = c["user_id"]
        entry: dict[str, Any] = {"user_id": uid, "message_count": c["message_count"]}
        if user_map and uid in user_map:
            entry["display_name"] = user_map[uid]
        contributors.append(entry)

    name_tokens = tokenize_channel_name(name)

    confidence_signals = sum(
        [
            bool(name_tokens),
            bool(topic) and not is_topic_stale(topic_last_set),
            bool(purpose),
            bool(pins),
            bool(bookmarks),
            len(messages) >= 5,
        ]
    )
    if confidence_signals >= 4:
        confidence = "high"
    elif confidence_signals >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "ok": True,
        "channel_id": channel_id,
        "name": name,
        "is_archived": is_archived,
        "is_private": is_private,
        "num_members": num_members,
        "signals": {
            "name_tokens": name_tokens,
            "topic": topic,
            "topic_stale": is_topic_stale(topic_last_set),
            "purpose": purpose,
            "pinned_messages": pins,
            "bookmarks": bookmarks,
            "recent_human_messages": messages,
            "top_contributors": contributors,
            "human_message_count": len(messages),
        },
        "confidence": confidence,
    }



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel-id",
        required=True,
        help="Slack channel ID (e.g. C0ABCDE1234)",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help=f"Max recent messages to fetch (default {DEFAULT_HISTORY_LIMIT})",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip the conversations.history call (faster, cheaper)",
    )
    parser.add_argument(
        "--no-pins",
        action="store_true",
        help="Skip the pins.list call",
    )
    parser.add_argument(
        "--no-bookmarks",
        action="store_true",
        help="Skip the bookmarks.list call",
    )
    parser.add_argument(
        "--replies",
        action="store_true",
        help="For messages with reply_count > 0, fetch the first few thread replies "
             "and include them as thread_messages on each message",
    )
    parser.add_argument(
        "--replies-limit",
        type=int,
        default=5,
        help="Max replies to fetch per thread when --replies is set (default 5)",
    )
    parser.add_argument(
        "--resolve-users",
        action="store_true",
        help="Resolve contributor user IDs to display names via users.info",
    )
    args = parser.parse_args()

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "error": "missing_token"}))
        return 1

    info = get_channel_info(args.channel_id, token)
    if not info.get("ok"):
        err = info.get("error", "unknown_error")
        print(json.dumps({"ok": False, "error": err, "channel_id": args.channel_id}))
        return 2

    pins = [] if args.no_pins else get_pinned_messages(args.channel_id, token)
    bookmarks = [] if args.no_bookmarks else get_bookmarks(args.channel_id, token)
    messages = (
        []
        if args.no_history
        else get_recent_human_messages(args.channel_id, token, args.history_limit)
    )

    # Optionally expand thread replies for high-activity messages
    if args.replies and messages:
        for msg in messages:
            if (msg.get("reply_count") or 0) > 0:
                msg["thread_messages"] = get_thread_replies(
                    args.channel_id, msg["ts"], token, args.replies_limit
                )

    # Optionally resolve user IDs to display names
    user_map: dict[str, str] | None = None
    if args.resolve_users and messages:
        unique_ids = list({m["user"] for m in messages if m.get("user")})
        user_map = resolve_user_ids(unique_ids, token)

    result = build_result(args.channel_id, info, pins, bookmarks, messages, user_map)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
