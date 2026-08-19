# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Counting for the preference policy.

Nothing here trains anything. It reads the audit trail, groups the user's own
corrections, and reports which groups have crossed the threshold. Writing the
policy sentence is left to the skill, because phrasing a preference in a way a
later run can act on needs judgment; deciding whether three corrections
happened does not.

The threshold is fixed on purpose. A system permitted to lower its own bar for
what counts as a preference eventually accepts everything.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

THRESHOLD = 3
MAX_POLICY_ENTRIES = 20

CORRECTION_TYPES = ("ignored", "priority_override")


@dataclass(frozen=True)
class Candidate:
    dimension: str      # what the corrections had in common
    value: str
    count: int
    event_type: str


def collect(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    """User-authored corrections only.

    Rows this agent changed are not corrections. Reading your own output back
    as evidence is how a system talks itself into a belief.
    """
    sql = ("SELECT e.event_type, i.sender, i.source, o.kind"
           "  FROM events e"
           "  JOIN obligations o ON o.id = e.obligation_id"
           "  JOIN items i ON i.source_id = o.source_id"
           " WHERE e.actor = 'user' AND e.event_type IN (?,?)")
    params: list[object] = list(CORRECTION_TYPES)
    if since:
        sql += " AND e.ts > ?"
        params.append(since)
    cols = ("event_type", "sender", "source", "kind")
    return [dict(zip(cols, r)) for r in conn.execute(sql, params)]


def _domain(sender: str | None) -> str | None:
    if sender and "@" in sender:
        return sender.rsplit("@", 1)[-1].lower()
    return None


def candidates(corrections: list[dict], threshold: int = THRESHOLD) -> list[Candidate]:
    """Groups that have crossed the threshold, strongest first.

    Grouped by sender, then sender domain, then source-and-kind — roughly in
    order of how often each turns out to describe something real.
    """
    counters: dict[str, Counter] = {"sender": Counter(), "domain": Counter(),
                                    "source_kind": Counter()}
    types: dict[tuple[str, str], Counter] = {}
    domain_senders: dict[str, set[str]] = {}

    for c in corrections:
        keys = []
        if c.get("sender"):
            keys.append(("sender", c["sender"]))
        d = _domain(c.get("sender"))
        if d:
            keys.append(("domain", d))
            domain_senders.setdefault(d, set()).add(c["sender"])
        if c.get("source"):
            keys.append(("source_kind", f"{c['source']}/{c.get('kind') or 'any'}"))
        for dim, val in keys:
            counters[dim][val] += 1
            types.setdefault((dim, val), Counter())[c["event_type"]] += 1

    out: list[Candidate] = []
    for dim in ("sender", "domain", "source_kind"):
        for value, count in counters[dim].items():
            if count < threshold:
                continue
            # One sender ignored three times is a fact about that sender. It
            # is not evidence about everyone who shares their mail domain —
            # and colleagues share the user's own domain, so promoting it
            # would suppress exactly the people who matter most. A domain rule
            # needs corroboration from more than one sender.
            if dim == "domain" and len(domain_senders.get(value, ())) < 2:
                continue
            dominant = types[(dim, value)].most_common(1)[0][0]
            out.append(Candidate(dim, value, count, dominant))
    return sorted(out, key=lambda c: (-c.count, c.dimension, c.value))


def cap(entries: list[str], limit: int = MAX_POLICY_ENTRIES) -> list[str]:
    """Newest first, oldest dropped past the limit.

    A policy longer than a screen stops being read, and an unread policy
    implies the system is adapting when it is not.
    """
    return entries[:limit]
