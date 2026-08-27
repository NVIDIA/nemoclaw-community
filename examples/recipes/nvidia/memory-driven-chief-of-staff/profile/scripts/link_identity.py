#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The user's answer to "are these the same person?".

Like `correct.py`, and for the same reason: the model must not be able to
manufacture this evidence. A display name matching, a handle matching — those
are why a question is asked, never why it is answered. Only the user answers,
and this is the only thing that writes an answer.

    python3 link_identity.py same slack:U01DANA email:dana@example.com
    python3 link_identity.py different slack:U01DANA email:d.okoro@example.com
    python3 link_identity.py list [--all]

Any number of identities may be named at once, because that is the shape of
the question the memory job asks — "these three all present as Dana Okoro" —
and answering it as three separate pairs is arithmetic the user should not
have to do.

**This is deliberately not part of any scheduled job.** The memory job writes
its pages, records what it noticed, and exits; nothing waits for an answer,
and an unanswered question costs nothing. Blocking a nightly job on a human
would make the job's completion depend on when somebody happened to read a
message, and the pages it can write without the answer are still worth
writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity  # noqa: E402
from _db import ensure_store, write_txn  # noqa: E402


def _identities(texts: list[str]) -> list[identity.Identity]:
    seen = []
    for text in texts:
        who = identity.parse(text)
        if who in seen:
            raise ValueError(f"{who} was named twice")
        seen.append(who)
    if len(seen) < 2:
        raise ValueError("name at least two identities")
    return seen


def _known(conn, who: identity.Identity) -> bool:
    return conn.execute(
        "SELECT 1 FROM items WHERE source = ? AND sender_key = ? LIMIT 1",
        (who.source, who.key)).fetchone() is not None


def _check_sources(conn, people: list[identity.Identity]) -> None:
    """Refuse a source this install has never heard of.

    The foreign key already refuses it, and says `FOREIGN KEY constraint
    failed` — which tells a user who mistyped `slak:U01DANA` nothing about
    what went wrong or what to type instead. The constraint stays; this is
    the message.

    Refusing rather than adding the source: a source appears when a connector
    ships, and inventing one here would let a typo create a namespace that
    silently matches nothing forever.
    """
    known = {row[0] for row in conn.execute("SELECT name FROM sources")}
    missing = sorted({w.source for w in people} - known)
    if missing:
        raise ValueError(
            f"no connector called {', '.join(missing)}; this install knows "
            f"{', '.join(sorted(known))}. An identity is `<source>:<key>`, "
            "and the source is the connector that collected it.")


def decide(texts: list[str], status: str) -> dict[str, object]:
    """Record one answer over every pair among the named identities.

    Stored pairwise even when the user answered about a group, so a later
    answer about one member does not have to unpick a group decision — and so
    `different` means what it says. Confirming a group of three is three
    pairs; rejecting one is also three, because "these are not one person"
    does not say which of them is the odd one out, and recording only some of
    the pairs would leave the rest to be asked again.
    """
    people = _identities(texts)
    unknown = []
    with write_txn() as conn:
        _check_sources(conn, people)
        for who in people:
            if not _known(conn, who):
                unknown.append(str(who))
        for a, b in combinations(people, 2):
            identity.record(conn, a, b, status)
        conflicts = identity.contradictions(conn)
    return {
        "identities": [str(w) for w in people],
        "status": status,
        "pairs": len(list(combinations(people, 2))),
        # Named rather than refused: an identity with no messages yet is a
        # normal state — a colleague whose account the user knows about
        # before the collector has seen them write.
        "not_seen_in_the_store": unknown,
        # Answers that no longer agree. The write is kept; see
        # `identity.contradictions` for why neither side is dropped.
        "conflicts": conflicts,
    }


def listing(everything: bool) -> dict[str, object]:
    with write_txn() as conn:
        answers = identity.decisions(conn)
        persons = identity.resolve(
            conn, [identity.Identity(s, k) for s, k in conn.execute(
                "SELECT DISTINCT source, sender_key FROM items"
                " WHERE sender_key IS NOT NULL")])
        conflicts = identity.contradictions(conn)
    groups = {}
    for (a, b), status in answers.items():
        if status != "confirmed":
            continue
        root = persons.of(a)
        groups[str(root)] = [str(x) for x in persons.group(a)]
    out: dict[str, object] = {"people": sorted(groups.values()),
                              "conflicts": conflicts}
    if everything:
        out["rejected"] = sorted(
            f"{a} / {b}" for (a, b), s in answers.items() if s == "rejected")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Say which identities are the same person.")
    sub = ap.add_subparsers(dest="command", required=True)

    same = sub.add_parser("same", help="one person, several accounts")
    same.add_argument("identities", nargs="+", metavar="source:key")

    diff = sub.add_parser("different", help="not the same person")
    diff.add_argument("identities", nargs="+", metavar="source:key")

    shown = sub.add_parser("list", help="what has been answered so far")
    shown.add_argument("--all", action="store_true",
                       help="include the pairs answered as different people")

    args = ap.parse_args(argv)
    ensure_store()
    try:
        if args.command == "list":
            report = listing(args.all)
        else:
            report = decide(args.identities,
                            "confirmed" if args.command == "same"
                            else "rejected")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
