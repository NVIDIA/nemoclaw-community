# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared opt-in and counterparty rules for user-authored message evidence."""

from datetime import datetime, timedelta, timezone
import json
import os

import exclusions

SETTINGS = {"email": "INTAKE_GRAPH_SENT_ITEMS", "slack": "INTAKE_SLACK_SELF_AUTHORED"}
PENDING_DAYS = 7


def enabled(source):
    name = SETTINGS[source]
    value = os.environ.get(name, "0").strip()
    if value not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1; collection was not started")
    return value == "1"


def pending_deadline(event_at):
    try:
        event = datetime.fromisoformat(event_at.replace("Z", "+00:00"))
        if event.tzinfo is None:
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    return (event.astimezone(timezone.utc) + timedelta(days=PENDING_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_pending(conn, now=None):
    """Attribute an eligible group message to its first qualifying responder.

    Match the connected account and thread; Slack also needs the channel.
    Email responders must be among the recorded recipients. An expired window
    may still resolve to an already-stored reply that occurred within it.
    Content never determines attribution. The caller owns the transaction.
    """
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rules = exclusions.load_rules()
    rows = conn.execute(
        "SELECT source_id, source, source_account, scope, thread_ref, event_at,"
        " counterparty_pending_until, sender_key, counterparty_candidates"
        " FROM items WHERE direction='outbound' AND counterparty_key IS NULL"
        " AND counterparty_pending_until IS NOT NULL"
        " ORDER BY counterparty_pending_until, source_id LIMIT 200").fetchall()
    resolved = 0
    for sid, source, account, scope, thread, event_at, deadline, author, candidates in rows:
        reply = None
        if account and thread:
            sql = ("SELECT sender, sender_key, sender_handle FROM items"
                   " WHERE source=? AND source_account=? AND thread_ref=?"
                   " AND direction='inbound' AND sender_key IS NOT NULL"
                   " AND sender_key IS NOT ? AND deleted_at IS NULL"
                   " AND julianday(event_at)>julianday(?)"
                   " AND julianday(event_at)<=julianday(?)")
            args = [source, account, thread, author, event_at, deadline]
            if source == "slack":
                sql += " AND scope=?"
                args.append(scope)
                eligible = sid == f"{scope}:{thread}"
            elif source == "email":
                try:
                    recipients = json.loads(candidates or "[]")
                except (ValueError, TypeError):
                    recipients = []
                eligible = (isinstance(recipients, list) and 0 < len(recipients) <= 500
                            and all(isinstance(key, str) for key in recipients))
                if eligible:
                    sql += " AND sender_key IN (" + ",".join("?" for _ in recipients) + ")"
                    args += recipients
            else:
                eligible = False
            if eligible:
                reply = conn.execute(sql + " ORDER BY julianday(event_at), source_id LIMIT 1", args).fetchone()
        if reply:
            name, key, handle = reply
            # New exclusions do not purge old rows, but they must prevent a
            # later resolver from attributing that retained text to this person.
            blocked = exclusions.excluded({"sender": name, "sender_id": key,
                                           "sender_address": key, "scope": scope}, rules)
            if not blocked:
                conn.execute(
                    "UPDATE items SET counterparty_name=?, counterparty_key=?,"
                    " counterparty_handle=?, counterparty_basis='reply',"
                    " counterparty_pending_until=NULL WHERE source_id=?",
                    (name, key, handle, sid))
                resolved += 1
            else:
                conn.execute("UPDATE items SET counterparty_pending_until=NULL WHERE source_id=?", (sid,))
        elif deadline <= now:
            conn.execute("UPDATE items SET counterparty_pending_until=NULL WHERE source_id=?", (sid,))
    return resolved
