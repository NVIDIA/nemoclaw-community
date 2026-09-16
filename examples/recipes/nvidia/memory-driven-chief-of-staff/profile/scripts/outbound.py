# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared opt-in and counterparty rules for user-authored message evidence."""

from datetime import datetime, timedelta, timezone
import json
import os

import exclusions

SETTINGS = {"email": "INTAKE_GRAPH_SENT_ITEMS", "slack": "INTAKE_SLACK_SELF_AUTHORED"}
PENDING_DAYS = 7
RESOLUTION_BATCH = 200
RESOLUTION_CURSOR = "outbound_resolution_cursor"


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


def _pending_batch(conn):
    """Continue a bounded keyset sweep, wrapping only after reaching its end."""
    saved = conn.execute("SELECT value FROM meta WHERE key=?", (RESOLUTION_CURSOR,)).fetchone()
    try:
        cursor = json.loads(saved[0]) if saved else None
        if not (isinstance(cursor, list) and len(cursor) == 2
                and all(isinstance(value, str) for value in cursor)):
            cursor = None
    except (ValueError, TypeError):
        # This is scheduling position, not evidence. Restarting costs a scan.
        cursor = None
    query = (
        "SELECT source_id, source, source_account, scope, thread_ref, event_at,"
        " counterparty_pending_until, sender_key, counterparty_candidates"
        " FROM items WHERE direction='outbound' AND counterparty_key IS NULL"
        " AND counterparty_pending_until IS NOT NULL")
    order = " ORDER BY counterparty_pending_until, source_id LIMIT ?"
    if cursor:
        rows = conn.execute(query + " AND (counterparty_pending_until,source_id)>(?,?)"
                            + order, (*cursor, RESOLUTION_BATCH)).fetchall()
        if rows:
            return rows
    return conn.execute(query + order, (RESOLUTION_BATCH,)).fetchall()


def resolve_pending(conn, now=None):
    """Attribute an eligible group message to its first qualifying responder.

    Match the connected account and thread; Slack also needs the channel.
    Email responders must be among the recorded recipients. Eligibility uses
    reply event time, including replies collected after the window elapsed.
    `now` remains accepted for compatibility; wall-clock expiry does not erase
    that event-time boundary. Content never determines attribution. The caller
    owns the transaction, including the work cursor.
    """
    rules = exclusions.load_rules()
    rows = _pending_batch(conn)
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
        # Unmatched rows retain their event-time deadline. A later collection
        # can supply an eligible reply without extending the seven-day window.
    if rows:
        last = rows[-1]
        conn.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key)"
            " DO UPDATE SET value=excluded.value",
            (RESOLUTION_CURSOR, json.dumps([last[6], last[0]])))
    else:
        conn.execute("DELETE FROM meta WHERE key=?", (RESOLUTION_CURSOR,))
    return resolved
