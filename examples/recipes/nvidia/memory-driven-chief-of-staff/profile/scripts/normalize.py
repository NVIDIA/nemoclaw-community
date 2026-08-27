# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turn source API responses into `items` rows.

Kept separate from the HTTP calls on purpose: normalization is where the
mistakes live, and this way it can be tested against recorded payloads with no
credentials and no network.

Both sources answer the same questions in different vocabulary, and this module
is where that translation is pinned down:

    Graph message id            -> source_id
    "<channel>:<ts>"            -> source_id          (a Slack ts is unique
                                                       only within a channel)
    parentFolderId / channel id -> scope
    conversationId / thread_ts  -> thread_ref
    receivedDateTime / ts       -> event_at           (ISO-8601 UTC; Slack
                                                       sends an epoch float)
    To recipient / im or mpim   -> addressing=direct
    @-mention in a channel      -> addressing=mentioned
    Cc only / channel broadcast -> addressing=broadcast
"""

from __future__ import annotations

import sys

import exclusions


import re
from datetime import datetime, timezone
from typing import Any

MENTION = re.compile(r"<@([A-Z0-9]+)>")


def _iso(dt: str) -> str:
    """Graph already sends ISO-8601; normalize the suffix so both agree."""
    return dt.replace("+00:00", "Z") if dt else ""


def _slack_ts_to_iso(ts: str) -> str:
    """Slack sends `"1723987200.123456"`. Seconds are enough for ordering."""
    return (datetime.fromtimestamp(float(ts), tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def _address_of(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    return (entry.get("emailAddress") or {}).get("address", "").lower()


def _display_of(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    ea = entry.get("emailAddress") or {}
    return ea.get("name") or ea.get("address") or ""


def graph_message_to_item(msg: dict[str, Any], user_address: str) -> dict[str, Any]:
    """One Graph message -> one `items` row.

    `user_address` decides addressing: being a To recipient is being asked;
    being copied is being informed.
    """
    me = (user_address or "").lower()
    to = {_address_of(r) for r in msg.get("toRecipients") or []}
    cc = {_address_of(r) for r in msg.get("ccRecipients") or []}

    if me and me in to:
        addressing = "direct"
    elif me and me in cc:
        addressing = "broadcast"
    else:
        # Distribution lists expand to neither, and a message that reached the
        # mailbox without naming the user is a broadcast by any useful test.
        addressing = "broadcast"

    body = msg.get("body") or {}
    return {
        "source_id": msg["id"],
        "source": "email",
        "scope": msg.get("parentFolderId") or "inbox",
        "thread_ref": msg.get("conversationId"),
        "event_at": _iso(msg.get("receivedDateTime", "")),
        "sender": _display_of(msg.get("from")),
        # Carried for the exclusion rules and dropped before the insert: it is
        # not in ITEM_COLUMNS, so it is matched on and never stored. `sender`
        # holds the display name when there is one, which means a domain rule
        # has nothing to match without this — the address is exactly what the
        # user wrote the rule against.
        "sender_address": _address_of(msg.get("from")),
        # The stable half. `sender` is the display name when there is one,
        # which two different people can share; the address is theirs.
        "sender_key": _address_of(msg.get("from")) or None,
        # Mail has no handle of its own — Graph gives a sender a name and an
        # address and nothing else — so this is *derived* from the address
        # rather than stated by the source. Said plainly because it changes
        # what it is worth as evidence: a handle matching another mail
        # identity's proves nothing new, since both come from the key that
        # already distinguishes them. Matching a handle from a different
        # source is a different matter.
        "sender_handle": (_address_of(msg.get("from")) or "").split("@")[0]
                         or None,
        "subject": msg.get("subject"),
        "body": body.get("content"),
        "permalink": msg.get("webLink"),
        "addressing": addressing,
        "unread": 0 if msg.get("isRead") else 1,
        # Stored, unlike `sender_address`: a removal reported later can only
        # be told apart from a move by asking about this, and by then the
        # message is no longer available to read it from.
        "internet_message_id": msg.get("internetMessageId"),
    }


def slack_message_to_item(
    msg: dict[str, Any],
    channel: dict[str, Any],
    user_id: str,
    sender_name: str | None = None,
    sender_handle: str | None = None,
) -> dict[str, Any]:
    """One Slack message -> one `items` row.

    `channel` needs `id` and `type` (`im`, `mpim`, `channel`, `group`).
    `sender_name` is the resolved display name when the caller has it; the raw
    user id is a poor thing to show a human, but it is better than nothing.
    """
    cid = channel["id"]
    ts = msg["ts"]

    ctype = channel.get("type", "")
    if ctype in {"im", "mpim"}:
        addressing = "direct"
    elif user_id and user_id in MENTION.findall(msg.get("text", "")):
        addressing = "mentioned"
    else:
        addressing = "broadcast"

    return {
        "source_id": f"{cid}:{ts}",
        "source": "slack",
        "scope": cid,
        # Slack marks only replies with thread_ts; a thread parent carries its
        # own ts there, so falling back to ts groups a parent with its replies.
        "thread_ref": msg.get("thread_ts") or ts,
        "event_at": _slack_ts_to_iso(ts),
        "sender": sender_name or msg.get("user"),
        # Same reason as the Graph address above. The collector resolves the
        # Slack user to a display name, which the person can change at will;
        # without the raw id a `U…` rule matches nothing.
        "sender_id": msg.get("user"),
        # The stable half, for the same reason: a display name is something
        # its owner can change, and two people can choose the same one.
        "sender_key": msg.get("user") or None,
        # Stated by the source, unlike mail's: Slack's `name` is the `@handle`
        # a colleague is addressed by. Unique in the workspace, and the person
        # can change it — readable, and not an identity.
        "sender_handle": sender_handle or None,
        "subject": None,
        "body": msg.get("text"),
        "permalink": msg.get("permalink"),
        # Slack tracks read state per channel, not per message.
        "unread": None,
        "addressing": addressing,
    }


ITEM_COLUMNS = (
    "source_id", "source", "scope", "thread_ref", "event_at",
    "sender", "sender_key", "sender_handle", "subject", "body", "permalink",
    "addressing", "unread",
    # Mail only. Slack has no equivalent and leaves it NULL; the collector
    # that needs it is the one that can tell a move from a deletion.
    "internet_message_id",
)


def insert_items(conn, items) -> int:
    """Idempotent on source_id, so re-reading a source window is harmless.

    Exclusion is applied here, and only here. Every writer goes through this
    function, so a sender or channel the user excluded never reaches the store
    no matter which collector found it — including collectors written later,
    which cannot forget a rule they never had to know about.

    Filtering at display would leave the text on disk, which is no use to
    somebody excluding their doctor or a channel where pay is discussed.

    A malformed rules file stops the insert rather than proceeding without it.
    The guarantee is that excluded content is never written; continuing past a
    file the user wrote in order to keep something out would breach exactly
    that, silently, and they would find out from the row on disk.
    """
    items, dropped = exclusions.partition(list(items))
    if dropped:
        # Said out loud, on stderr, because a silent drop and an empty mailbox
        # look identical from the outside.
        print(f"exclusions: {dropped} message(s) not stored", file=sys.stderr)
    placeholders = ",".join("?" * len(ITEM_COLUMNS))
    rows = [tuple(item.get(c) for c in ITEM_COLUMNS) for item in items]
    before = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.executemany(
        f"INSERT OR IGNORE INTO items({','.join(ITEM_COLUMNS)}) VALUES ({placeholders})",
        rows)

    # Fill in an identity a row does not have yet.
    #
    # `INSERT OR IGNORE` leaves an existing row alone, so a store upgraded to
    # v3 keeps `sender_key IS NULL` on everything it collected before — even
    # when the collector re-reads the very same message and now knows the
    # answer. Nothing else about the row is touched, and the value comes from
    # that message rather than from matching a name against another row, so
    # this cannot merge two people the way a name-based backfill would.
    #
    # It is a floor, not a guarantee: it reaches what the collectors re-read,
    # which for a rolling window is the recent past and nothing older. What
    # stays unkeyed is handled by refusing to guess — see `people()`.
    conn.executemany(
        "UPDATE items SET sender_key = ?"
        "  WHERE source_id = ? AND sender_key IS NULL",
        [(item["sender_key"], item["source_id"]) for item in items
         if item.get("sender_key") and item.get("source_id")])
    return conn.execute("SELECT count(*) FROM items").fetchone()[0] - before