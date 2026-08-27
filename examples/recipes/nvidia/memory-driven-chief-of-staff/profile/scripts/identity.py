#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Who is one person, across however many places they write from.

A person is a set of identities, not one. `sender_key` gives a stable
identity per source; this module is what joins them, and what refuses to.

The rules, in the order they matter:

1. **An identity is a `(source, key)` pair, never a bare key.** Two sources
   can mint the same string — a chat id and a login can collide, and nothing
   stops them — and merging two people because their opaque ids matched would
   be silent and unrecoverable. The store already carries `source` beside
   `sender_key`; this module is where the pair is treated as one value.

2. **Only the user joins identities.** No display name, no matching handle,
   no heuristic. The whole reason the store keeps a stable identity is that
   guessing from a name puts two people on one page, and a guess dressed up
   as a confident link is worse than the split it replaced.

3. **Answers compose.** Links are stored pairwise and resolved with a
   disjoint set, so confirming A~B and B~C makes A~C true without asking
   again, and the fourth identity is one more pair rather than a new shape.
   Nothing here counts to two.

4. **A dismissed candidate stays dismissed.** Rejections are recorded, not
   just absences of confirmation, so the next run does not re-propose what
   the user has already answered. An unresolved question re-asked nightly is
   how a job that should be idle wakes the agent every night forever.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Iterable, NamedTuple

# A source name appears before the first colon in an identity's text form, so
# it may not contain one. Keys may: a Teams id looks like `29:1a2b…`.
SOURCE = re.compile(r"^[a-z0-9_]+$")


class Identity(NamedTuple):
    """One account, in one system."""

    source: str
    key: str

    def __str__(self) -> str:
        return f"{self.source}:{self.key}"


def parse(text: str) -> Identity:
    """`slack:U01DANA` -> Identity('slack', 'U01DANA').

    Split on the *first* colon only. A key may contain colons — a Teams
    conversation id is `29:1a2b…` — and splitting on the last, or on all of
    them, silently truncates the identity of every such account to something
    that matches nobody.
    """
    source, _, key = (text or "").partition(":")
    if not key or not SOURCE.match(source):
        raise ValueError(
            f"{text!r} is not an identity; expected `<source>:<key>` with a "
            "source of lowercase letters, digits or underscores")
    return Identity(source, key)


def _ordered(a: Identity, b: Identity) -> tuple[Identity, Identity]:
    """The pair in the order the table stores it.

    One row per pair, smaller side left, so `(A,B)` and `(B,A)` cannot both
    exist and disagree about the same question. The database enforces it too;
    this is where the ordering is applied rather than discovered.
    """
    return (a, b) if a < b else (b, a)


def record(conn: sqlite3.Connection, a: Identity, b: Identity,
           status: str) -> None:
    """Write the user's answer about one pair, replacing any earlier one.

    Replacing rather than refusing: people change their minds, and a stored
    answer that cannot be corrected is worse than no answer, because the
    candidate never comes back to be asked again.
    """
    if status not in ("confirmed", "rejected"):
        raise ValueError(f"{status!r} is not confirmed or rejected")
    if a == b:
        raise ValueError("an identity is already itself")
    left, right = _ordered(a, b)
    conn.execute(
        "INSERT INTO identity_links(left_source, left_key, right_source,"
        "                           right_key, status)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(left_source, left_key, right_source, right_key)"
        "   DO UPDATE SET status = excluded.status,"
        "                 decided_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (left.source, left.key, right.source, right.key, status))


def decisions(conn: sqlite3.Connection) -> dict[tuple[Identity, Identity], str]:
    """Every answer the user has given, keyed by the ordered pair."""
    return {
        (Identity(ls, lk), Identity(rs, rk)): status
        for ls, lk, rs, rk, status in conn.execute(
            "SELECT left_source, left_key, right_source, right_key, status"
            "  FROM identity_links")
    }


class Persons:
    """Identities grouped into people, by the user's confirmations alone.

    A disjoint set. Grouping is not a pairwise question — asking "are these
    two the same" for every pair of a person's four identities is six
    questions where three answers suffice — and a disjoint set is what turns
    the answers given into the grouping implied.
    """

    def __init__(self, links: Iterable[tuple[Identity, Identity]] = ()):
        self._parent: dict[Identity, Identity] = {}
        for a, b in links:
            self.join(a, b)

    def _find(self, node: Identity) -> Identity:
        root = self._parent.setdefault(node, node)
        while root != self._parent[root]:
            root = self._parent[root]
        # Path compression, so a person with many identities does not get
        # slower to resolve as more are linked.
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def join(self, a: Identity, b: Identity) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            # Smaller root wins, so the representative of a person does not
            # depend on the order the links were read in — which would make
            # a page name change between runs for no reason.
            low, high = _ordered(ra, rb)
            self._parent[high] = low

    def of(self, node: Identity) -> Identity:
        """The identity that stands for this person.

        Deterministic: the lexicographically smallest identity in the set, so
        two runs over the same links agree, and adding an identity that sorts
        later does not rename anybody.
        """
        return self._find(node)

    def group(self, node: Identity) -> list[Identity]:
        root = self._find(node)
        return sorted(n for n in self._parent if self._find(n) == root)


def resolve(conn: sqlite3.Connection,
            seen: Iterable[Identity] = ()) -> Persons:
    """Group the identities in the store by the user's confirmed links.

    `seen` seeds identities that have no link at all, so a person with one
    identity is still a person rather than an absence.
    """
    confirmed = [pair for pair, status in decisions(conn).items()
                 if status == "confirmed"]
    persons = Persons(confirmed)
    for node in seen:
        persons.of(node)
    return persons


def contradictions(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Pairs the user rejected that their other answers have joined anyway.

    Confirm A~B and B~C and A~C follows, even if A~C was rejected earlier.
    Transitivity does not care, and neither answer is obviously the wrong
    one: the rejection may be stale, or one of the confirmations may be a
    mistake. So this reports the conflict instead of resolving it, and the
    grouping keeps the confirmations — dropping them would silently split a
    person whose other links the user did confirm.
    """
    answers = decisions(conn)
    persons = Persons([p for p, s in answers.items() if s == "confirmed"])
    found = []
    for (a, b), status in sorted(answers.items()):
        if status == "rejected" and persons.of(a) == persons.of(b):
            found.append({
                "rejected": f"{a} and {b}",
                "joined_by": " -> ".join(str(n) for n in persons.group(a)),
                "detail": "these were answered as different people, and other "
                          "confirmations since have joined them anyway",
            })
    return found


def candidates(rows: Iterable[tuple[Identity, str, str | None]],
               answers: dict[tuple[Identity, Identity], str],
               persons: Persons) -> list[dict[str, object]]:
    """Groups of identities that may be one person, for the user to answer.

    `rows` is `(identity, display_name, handle)` per identity seen in the
    window. Two things are treated as worth asking about, in this order:

    - a shared **handle** across different sources. A handle is unique within
      its own source, so `slack:dana` and `github:dana` being the same person
      is a real possibility, where two mail addresses whose local parts match
      is not news — that value was derived from the key that already tells
      them apart.
    - a shared **display name**. Weaker, and common enough to be worth asking
      about only because a colleague usually presents the same name
      everywhere.

    Neither is acted on. Both produce a question.

    A group is proposed only when it contains identities not already joined,
    and only when the user has not already answered every pair in it. Groups,
    not pairs, because one question about three identities beats three.
    """
    by_handle: dict[str, set[Identity]] = {}
    by_name: dict[str, set[Identity]] = {}
    display: dict[Identity, str] = {}
    for who, name, handle in rows:
        display[who] = name
        if handle:
            by_handle.setdefault(handle.strip().casefold(), set()).add(who)
        if name:
            by_name.setdefault(name.strip().casefold(), set()).add(who)

    # One question per set of identities, even when several signals point at
    # the same set. Handles are considered first, so a group that shares both
    # is reported under the stronger reason rather than twice.
    proposals = []
    asked: set[tuple[Identity, ...]] = set()
    for reason, buckets in (("shared handle", by_handle),
                            ("shared display name", by_name)):
        for value, members in sorted(buckets.items()):
            if len(members) < 2:
                continue
            if len({m.source for m in members}) < 2:
                # One source, one namespace: two distinct keys there are two
                # distinct accounts, and the source itself would not let them
                # share a handle. Nothing to ask.
                continue
            if len({persons.of(m) for m in members}) < 2:
                continue  # already one person
            group = sorted(members)
            if tuple(group) in asked:
                continue
            if all(answers.get(_ordered(a, b)) is not None
                   for i, a in enumerate(group) for b in group[i + 1:]):
                continue  # every pair already answered
            asked.add(tuple(group))
            proposals.append({
                "identities": [str(m) for m in group],
                "display_names": sorted({display.get(m) or "" for m in group}),
                "reason": reason,
                "value": value,
            })
    return proposals
