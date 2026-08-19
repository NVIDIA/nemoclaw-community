#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fetch bounded Slack history with coverage and source-link metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from slack_api_common import get_slack_bot_token

API_BASE = "https://slack.com/api"
CHANNEL_ID_RE = re.compile(r"^[CGD][A-Z0-9]{8,}$")
MAX_MESSAGE_LIMIT = 200
MAX_PAGE_CAP = 25
MAX_THREAD_CAP = 10
MAX_REPLY_LIMIT = 20
MAX_THREAD_PAGE_CAP = 5
MAX_PAGE_SIZE = 100
MAX_TEXT_CHARS = 4000

SKIP_SUBTYPES = {
    "bot_message",
    "channel_archive",
    "channel_join",
    "channel_leave",
    "channel_name",
    "channel_purpose",
    "channel_topic",
    "channel_unarchive",
    "ekm_access_denied",
    "message_deleted",
    "message_replied",
    "tombstone",
}

ApiCall = Callable[[str, str, dict[str, str]], dict[str, Any]]


class SlackApiFailure(RuntimeError):
    """A sanitized Slack API or transport failure."""

    def __init__(
        self,
        stage: str,
        error: str,
        *,
        needed: str | None = None,
        provided: str | None = None,
        retry_after: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(error)
        self.stage = stage
        self.error = error
        self.needed = needed
        self.provided = provided
        self.retry_after = retry_after
        self.http_status = http_status

    def result(self, channel_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "channel_id": channel_id,
            "stage": self.stage,
            "error": self.error,
        }
        for key, value in (
            ("needed", self.needed),
            ("provided", self.provided),
            ("retry_after", self.retry_after),
            ("http_status", self.http_status),
        ):
            if value not in (None, ""):
                result[key] = value
        return result


def slack_get(token: str, method: str, params: dict[str, str]) -> dict[str, Any]:
    """Call one Slack Web API GET method without exposing the access token."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{API_BASE}/{method}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 429:
            return {
                "ok": False,
                "error": "rate_limited",
                "http_status": 429,
                "retry_after": error.headers.get("Retry-After"),
            }
        return {
            "ok": False,
            "error": "http_error",
            "http_status": error.code,
        }
    except OSError:
        return {"ok": False, "error": "network_error"}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid_json"}


def checked_call(
    api_call: ApiCall,
    token: str,
    method: str,
    params: dict[str, str],
    stage: str,
) -> dict[str, Any]:
    data = api_call(token, method, params)
    if not isinstance(data, dict):
        raise SlackApiFailure(stage, "invalid_response")
    if not data.get("ok"):
        error_code = str(data.get("error") or "unknown_error")
        if error_code == "ratelimited":
            error_code = "rate_limited"
        raise SlackApiFailure(
            stage,
            error_code,
            needed=data.get("needed"),
            provided=data.get("provided"),
            retry_after=data.get("retry_after"),
            http_status=data.get("http_status"),
        )
    return data


def normalize_time_boundary(value: str) -> str:
    """Normalize a Slack timestamp or ISO 8601 timestamp for API use."""
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            instant = dt.datetime.fromisoformat(iso_value)
        except ValueError as error:
            raise ValueError(
                "expected a Slack timestamp or ISO 8601 timestamp"
            ) from error
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=dt.timezone.utc)
        parsed = Decimal(str(instant.timestamp()))
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("timestamp must be a finite non-negative value")
    normalized = format(parsed, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def timestamp_iso(value: str, stage: str = "history") -> str:
    try:
        instant = dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise SlackApiFailure(stage, "invalid_message_timestamp") from error
    return instant.isoformat(timespec="seconds").replace("+00:00", "Z")


def citation_for(timestamp: str, user_id: str, permalink: str) -> str:
    """Return a Markdown citation that identifies one retrieved Slack message."""
    instant = dt.datetime.fromtimestamp(float(timestamp), tz=dt.timezone.utc)
    label = instant.strftime("%Y-%m-%d %H:%M UTC")
    return f"[{label} — {user_id}]({permalink})"


def is_human_message(message: dict[str, Any]) -> bool:
    if message.get("bot_id") or message.get("subtype") in SKIP_SUBTYPES:
        return False
    if not message.get("user"):
        return False
    return bool(str(message.get("text") or "").strip())


def next_cursor(data: dict[str, Any]) -> str:
    metadata = data.get("response_metadata") or {}
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("next_cursor") or "").strip()


def range_metadata(oldest: str, latest: str) -> dict[str, str | None]:
    return {
        "oldest": oldest or None,
        "oldest_timestamp": timestamp_iso(oldest) if oldest else None,
        "latest": latest or None,
        "latest_timestamp": timestamp_iso(latest) if latest else None,
    }


def update_range(current: list[Decimal], messages: list[dict[str, Any]]) -> None:
    for message in messages:
        try:
            timestamp = Decimal(str(message.get("ts") or ""))
            if timestamp.is_finite():
                current.append(timestamp)
        except InvalidOperation:
            continue


def message_timestamp(message: dict[str, Any], stage: str) -> Decimal:
    try:
        timestamp = Decimal(str(message.get("ts") or ""))
    except InvalidOperation as error:
        raise SlackApiFailure(stage, "invalid_message_timestamp") from error
    if not timestamp.is_finite():
        raise SlackApiFailure(stage, "invalid_message_timestamp")
    return timestamp


def reply_count(message: dict[str, Any]) -> int:
    try:
        return max(0, int(message.get("reply_count") or 0))
    except (TypeError, ValueError):
        return 0


def permalink_for(
    api_call: ApiCall,
    token: str,
    channel_id: str,
    timestamp: str,
    cache: dict[str, str],
) -> str:
    if timestamp in cache:
        return cache[timestamp]
    data = checked_call(
        api_call,
        token,
        "chat.getPermalink",
        {"channel": channel_id, "message_ts": timestamp},
        "permalink",
    )
    permalink = str(data.get("permalink") or "").strip()
    if not permalink:
        raise SlackApiFailure("permalink", "missing_permalink")
    cache[timestamp] = permalink
    return permalink


def source_message(
    message: dict[str, Any],
    *,
    channel_id: str,
    api_call: ApiCall,
    token: str,
    permalink_cache: dict[str, str],
    root_timestamp: str | None = None,
    stage: str = "history",
) -> dict[str, Any]:
    timestamp = str(message.get("ts") or "").strip()
    if not timestamp:
        raise SlackApiFailure(stage, "missing_message_timestamp")
    iso_timestamp = timestamp_iso(timestamp, stage)
    user_id = str(message.get("user") or "unknown-user")
    permalink = permalink_for(
        api_call,
        token,
        channel_id,
        timestamp,
        permalink_cache,
    )
    raw_text = str(message.get("text") or "")
    rendered: dict[str, Any] = {
        "ts": timestamp,
        "timestamp": iso_timestamp,
        "user_id": user_id,
        "text": raw_text[:MAX_TEXT_CHARS],
        "text_truncated": len(raw_text) > MAX_TEXT_CHARS,
        "permalink": permalink,
        "citation": citation_for(timestamp, user_id, permalink),
        "reply_count": reply_count(message),
    }
    thread_timestamp = root_timestamp or str(message.get("thread_ts") or "").strip()
    if thread_timestamp:
        rendered["thread_root_ts"] = thread_timestamp
    return rendered


def fetch_history_pages(
    api_call: ApiCall,
    token: str,
    channel_id: str,
    *,
    oldest: str,
    latest: str,
    message_limit: int,
    page_cap: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    inspected_timestamps: list[Decimal] = []
    inspected_messages = 0
    pages = 0
    cursor = ""
    has_more = False
    fallback_latest = ""
    fallback_unavailable = False
    page_latest = latest
    workspace_history_limited = False
    extra_human_message = False
    page_size = min(MAX_PAGE_SIZE, message_limit)

    while pages < page_cap:
        params = {
            "channel": channel_id,
            "limit": str(page_size),
            "inclusive": "false" if fallback_latest else "true",
        }
        if oldest:
            params["oldest"] = oldest
        if page_latest:
            params["latest"] = page_latest
        if cursor:
            params["cursor"] = cursor

        data = checked_call(
            api_call,
            token,
            "conversations.history",
            params,
            "history",
        )
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list) or not all(
            isinstance(message, dict) for message in raw_messages
        ):
            raise SlackApiFailure("history", "invalid_messages")

        pages += 1
        inspected_messages += len(raw_messages)
        update_range(inspected_timestamps, raw_messages)
        for message in raw_messages:
            if not isinstance(message, dict) or not is_human_message(message):
                continue
            message_timestamp(message, "history")
            if len(selected) < message_limit:
                selected.append(message)
            else:
                extra_human_message = True

        cursor = next_cursor(data)
        has_more = bool(data.get("has_more"))
        fallback_latest = ""
        fallback_unavailable = False
        if has_more and not cursor:
            page_timestamps: list[Decimal] = []
            update_range(page_timestamps, raw_messages)
            if page_timestamps:
                candidate = min(page_timestamps)
                if (not oldest or candidate > Decimal(oldest)) and (
                    not page_latest or candidate < Decimal(page_latest)
                ):
                    fallback_latest = format(candidate, "f")
                else:
                    fallback_unavailable = True
            else:
                fallback_unavailable = True
        workspace_history_limited = workspace_history_limited or bool(
            data.get("is_limited")
        )
        if len(selected) >= message_limit:
            break
        if cursor:
            continue
        if fallback_latest and pages < page_cap:
            page_latest = fallback_latest
            continue
        if not cursor:
            break

    truncation_reasons: list[str] = []
    if len(selected) >= message_limit and (extra_human_message or cursor or has_more):
        truncation_reasons.append("message_limit")
    if (
        (cursor or fallback_latest)
        and pages >= page_cap
        and "message_limit" not in truncation_reasons
    ):
        truncation_reasons.append("page_cap")
    if has_more and not cursor and fallback_unavailable:
        truncation_reasons.append("history_has_more_without_cursor")
    if workspace_history_limited:
        truncation_reasons.append("workspace_history_limit")

    retrieved_oldest = str(min(inspected_timestamps)) if inspected_timestamps else ""
    retrieved_latest = str(max(inspected_timestamps)) if inspected_timestamps else ""
    coverage = {
        "requested_range": range_metadata(oldest, latest),
        "retrieved_range": range_metadata(retrieved_oldest, retrieved_latest),
        "pages": pages,
        "inspected_messages": inspected_messages,
        "human_messages": len(selected),
        "message_limit": message_limit,
        "page_cap": page_cap,
        "complete": not truncation_reasons,
        "truncated": bool(truncation_reasons),
        "truncation_reasons": truncation_reasons,
    }
    selected.sort(key=lambda message: message_timestamp(message, "history"))
    return selected, coverage


def fetch_thread_replies(
    api_call: ApiCall,
    token: str,
    channel_id: str,
    root_timestamp: str,
    *,
    reply_limit: int,
    page_cap: int,
    permalink_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    inspected_messages = 0
    pages = 0
    cursor = ""
    has_more = False
    extra_human_reply = False
    page_size = min(MAX_PAGE_SIZE, reply_limit + 1)

    while pages < page_cap:
        params = {
            "channel": channel_id,
            "ts": root_timestamp,
            "limit": str(page_size),
            "inclusive": "true",
        }
        if cursor:
            params["cursor"] = cursor
        data = checked_call(
            api_call,
            token,
            "conversations.replies",
            params,
            "thread_replies",
        )
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            raise SlackApiFailure("thread_replies", "invalid_messages")

        pages += 1
        for message in raw_messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("ts") or "") == root_timestamp:
                continue
            inspected_messages += 1
            if not is_human_message(message):
                continue
            message_timestamp(message, "thread_replies")
            if len(selected) < reply_limit:
                selected.append(message)
            else:
                extra_human_reply = True

        cursor = next_cursor(data)
        has_more = bool(data.get("has_more"))
        if len(selected) >= reply_limit or not cursor:
            break

    truncation_reasons: list[str] = []
    if len(selected) >= reply_limit and (extra_human_reply or cursor or has_more):
        truncation_reasons.append("reply_limit")
    if cursor and pages >= page_cap and "reply_limit" not in truncation_reasons:
        truncation_reasons.append("thread_page_cap")
    if has_more and not cursor:
        truncation_reasons.append("replies_have_more_without_cursor")

    selected.sort(key=lambda message: message_timestamp(message, "thread_replies"))
    replies = [
        source_message(
            message,
            channel_id=channel_id,
            api_call=api_call,
            token=token,
            permalink_cache=permalink_cache,
            root_timestamp=root_timestamp,
            stage="thread_replies",
        )
        for message in selected
    ]
    coverage = {
        "root_ts": root_timestamp,
        "pages": pages,
        "inspected_messages": inspected_messages,
        "human_replies": len(replies),
        "reply_limit": reply_limit,
        "page_cap": page_cap,
        "complete": not truncation_reasons,
        "truncated": bool(truncation_reasons),
        "truncation_reasons": truncation_reasons,
    }
    return replies, coverage


def collect_channel_history(
    token: str,
    channel_id: str,
    *,
    oldest: str = "",
    latest: str = "",
    message_limit: int = 50,
    page_cap: int = 10,
    include_replies: bool = False,
    thread_cap: int = 10,
    reply_limit: int = 20,
    thread_page_cap: int = 3,
    api_call: ApiCall = slack_get,
) -> dict[str, Any]:
    """Return bounded, source-linked history or one sanitized failure."""
    try:
        raw_messages, coverage = fetch_history_pages(
            api_call,
            token,
            channel_id,
            oldest=oldest,
            latest=latest,
            message_limit=message_limit,
            page_cap=page_cap,
        )
        permalink_cache: dict[str, str] = {}
        messages = [
            source_message(
                message,
                channel_id=channel_id,
                api_call=api_call,
                token=token,
                permalink_cache=permalink_cache,
            )
            for message in raw_messages
        ]

        thread_result: dict[str, Any] = {
            "requested": include_replies,
            "roots_available": 0,
            "roots_expanded": 0,
            "replies_included": 0,
            "thread_cap": thread_cap,
            "reply_limit": reply_limit,
            "page_cap_per_thread": thread_page_cap,
            "complete": True,
            "truncated": False,
            "truncation_reasons": [],
            "items": [],
        }
        if include_replies:
            roots = [
                (raw, rendered)
                for raw, rendered in zip(raw_messages, messages)
                if reply_count(raw) > 0
                and (
                    not raw.get("thread_ts")
                    or str(raw.get("thread_ts")) == str(raw.get("ts"))
                )
            ]
            thread_result["roots_available"] = len(roots)
            for raw, rendered in roots[:thread_cap]:
                replies, reply_coverage = fetch_thread_replies(
                    api_call,
                    token,
                    channel_id,
                    str(raw.get("ts") or ""),
                    reply_limit=reply_limit,
                    page_cap=thread_page_cap,
                    permalink_cache=permalink_cache,
                )
                rendered["thread_replies"] = replies
                thread_result["items"].append(reply_coverage)
                thread_result["roots_expanded"] += 1
                thread_result["replies_included"] += len(replies)

            reasons: list[str] = []
            if len(roots) > thread_cap:
                reasons.append("thread_cap")
            for item in thread_result["items"]:
                for reason in item["truncation_reasons"]:
                    if reason not in reasons:
                        reasons.append(reason)
            thread_result["complete"] = not reasons
            thread_result["truncated"] = bool(reasons)
            thread_result["truncation_reasons"] = reasons

        return {
            "ok": True,
            "channel_id": channel_id,
            "empty": not messages,
            "coverage": coverage,
            "threads": thread_result,
            "messages": messages,
        }
    except SlackApiFailure as error:
        return error.result(channel_id)


def bounded_positive_int(name: str, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        parsed = int(value)
        if parsed < 1 or parsed > maximum:
            raise argparse.ArgumentTypeError(f"{name} must be between 1 and {maximum}")
        return parsed

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-id", required=True, help="Slack channel ID")
    parser.add_argument(
        "--oldest",
        default="",
        help="Oldest inclusive Slack timestamp or ISO 8601 timestamp",
    )
    parser.add_argument(
        "--latest",
        default="",
        help="Latest inclusive Slack timestamp or ISO 8601 timestamp",
    )
    parser.add_argument(
        "--message-limit",
        type=bounded_positive_int("message limit", MAX_MESSAGE_LIMIT),
        default=50,
        help=f"Maximum human messages to return (default 50; maximum {MAX_MESSAGE_LIMIT})",
    )
    parser.add_argument(
        "--page-cap",
        type=bounded_positive_int("page cap", MAX_PAGE_CAP),
        default=10,
        help=f"Maximum history pages to inspect (default 10; maximum {MAX_PAGE_CAP})",
    )
    parser.add_argument(
        "--replies",
        action="store_true",
        help="Include bounded thread replies",
    )
    parser.add_argument(
        "--thread-cap",
        type=bounded_positive_int("thread cap", MAX_THREAD_CAP),
        default=10,
        help=f"Maximum thread roots to expand (default 10; maximum {MAX_THREAD_CAP})",
    )
    parser.add_argument(
        "--reply-limit",
        type=bounded_positive_int("reply limit", MAX_REPLY_LIMIT),
        default=20,
        help=f"Maximum human replies per thread (default 20; maximum {MAX_REPLY_LIMIT})",
    )
    parser.add_argument(
        "--thread-page-cap",
        type=bounded_positive_int("thread page cap", MAX_THREAD_PAGE_CAP),
        default=3,
        help=(
            "Maximum pages to inspect per thread "
            f"(default 3; maximum {MAX_THREAD_PAGE_CAP})"
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not CHANNEL_ID_RE.fullmatch(args.channel_id):
        parser.error("--channel-id must be a Slack channel ID such as C0123456789")
    try:
        oldest = normalize_time_boundary(args.oldest)
        latest = normalize_time_boundary(args.latest)
    except ValueError as error:
        parser.error(str(error))
    if oldest and latest and Decimal(oldest) > Decimal(latest):
        parser.error("--oldest must not be later than --latest")

    token = get_slack_bot_token()
    if not token:
        print(
            json.dumps(
                {"ok": False, "stage": "authentication", "error": "missing_token"}
            )
        )
        return 1

    result = collect_channel_history(
        token,
        args.channel_id,
        oldest=oldest,
        latest=latest,
        message_limit=args.message_limit,
        page_cap=args.page_cap,
        include_replies=args.replies,
        thread_cap=args.thread_cap,
        reply_limit=args.reply_limit,
        thread_page_cap=args.thread_page_cap,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
