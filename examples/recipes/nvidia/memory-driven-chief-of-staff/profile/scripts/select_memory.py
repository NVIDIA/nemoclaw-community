# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cron pre-step for the memory-writing pass.

The memory is what makes this recipe more than a mail sorter: ranking reserves
its top tier for work the person has *chosen*, and only `attention/` and
`goals/` can answer that. Until something writes those pages, nothing can ever
reach `high` and the assistant is left measuring how loudly the outside world
is asking — which is the thing it exists not to do.

The other three memory jobs do not fill that gap and are not meant to. Repair
checks invariants, consolidation compacts pages that grew past their ceiling,
preference-update writes the policy. All three maintain a memory; none creates
one.

So this selects the evidence and the agent writes the pages. The split matters
for the same reason it does elsewhere in this recipe: arithmetic that can be
done in Python is not left to a prompt. Who the recurring correspondents are,
how many exchanges there have been, which of them already have a page, and
which pages have gone stale are all counting problems, answered here. Which of
them is worth a page, and what it should say, is judgment, answered by the
model.

Emits `{"wakeAgent": false}` when there is nothing new to write, so a quiet day
costs no tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta, timezone

from _db import ensure_store, write_txn

# How many exchanges before somebody is worth a page.
#
# One message is an event, not a relationship. Two is the smallest number that
# distinguishes a correspondent from a notification, and it is the threshold
# the production system this recipe is adapted from uses.
PEOPLE_THRESHOLD = 2

# How far back the evidence window reaches. The store holds more; the point of
# a page is who is around *now*.
#
# Thirty days is the default rather than the rule: a month is long enough that
# somebody on leave for a fortnight still has a page, and short enough that a
# collaborator from two projects ago stops competing for one. Move it with
# `MEMORY_WINDOW_DAYS` — a wider window on a first run backfills a memory from
# the history already collected, a narrower one keeps the pages to who is
# around this week.
WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 3650

# Bounds on one pass, for the same reason the intake slice is bounded: a turn
# that tries to write forty pages writes forty bad ones.
MAX_PEOPLE = 8
MAX_INTERACTIONS = 12

# Senders that are machinery rather than people. A page for a build server
# teaches the ranking job nothing and costs a turn to maintain.
AUTOMATED = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|alerts?|mailer|"
    r"automated|jenkins|gitlab|github|jira|bot)\b", re.I)


def bounded_days(name: str, default: int) -> int:
    """Read a positive, bounded day count from the environment.

    Same shape as the other bounded settings here, and for the same reason: a
    zero window selects nobody and reports a quiet day that is not one, and a
    negative puts the cutoff in the future so every sender qualifies at once.
    Both are the kind of mistake only noticed by its consequences.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"{name} must be a whole number of days between 1 and "
            f"{MAX_WINDOW_DAYS}; got {raw!r}")
    if value < 1 or value > MAX_WINDOW_DAYS:
        raise SystemExit(
            f"{name} must be between 1 and {MAX_WINDOW_DAYS}; got {value}")
    return value


def seed_root():
    """The packaged pages a fresh memory starts from.

    Shipped as files rather than assembled in code, the way the production
    system this recipe is adapted from does it: its Stage-0 bootstrap copies
    packaged seed pages into the workspace, idempotently and without
    overwriting, and logs that it did. A page written by string concatenation
    at runtime is a second, invisible copy of the schema that drifts from
    `schema.md` the first time either changes.
    """
    return Path(__file__).resolve().parent.parent / "seed"


def bootstrap(root) -> list[str]:
    """Copy in whatever the memory is missing. Never overwrite.

    A clean install has no `workspace/memory/` at all, so the first scheduled
    run began by reading an index that did not exist and appending to a log
    that did not exist. It worked, because the model improvised — which means
    the structure every page is then validated against was whatever it
    improvised that night, and the repair job's first act was to disagree.

    Seeding the attention pages matters beyond having a valid file there.
    `current_priorities.md` is what the ranking job gates its top tier on, and
    its correct initial state is not "absent" but "nothing chosen yet, and
    here is what would count" — a claim the schema can check and a person can
    read. The `updated: 1970-01-01` in the packaged copy is deliberate: it is
    stale on arrival, so the first pass is told to look rather than told
    everything is current.

    Returns the relative paths written, so the caller can report them.
    """
    written: list[str] = []
    for folder in (root, root / "people", root / "attention"):
        folder.mkdir(parents=True, exist_ok=True)

    for source in sorted(seed_root().rglob("*.md")):
        relative = source.relative_to(seed_root())
        target = root / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(str(relative))

    if written:
        log = root / "log.md"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{stamp}] bootstrap\n"
                         f"- seeded {', '.join(written)}\n")
    return written


def memory_root():
    from _db import ledger_path
    return ledger_path().parent.parent / "memory"


def slug(name: str) -> str:
    """`Dana Okoro` -> `dana_okoro`, per the schema's filename rule.

    A page name is a durable identity: two people who reduce to the same one
    share a page, and the second overwrites the first. The naive form of this
    lost that in three ways at once, all of them on real names. A name written
    in a script with no Latin letters reduced to the empty string, so everyone
    in that script shared one nameless page. A name with diacritics lost the
    letters the rule did not recognise, producing a different person. And
    `A-B` and `A B` both became `a_b`, so the second overwrote the first.

    So: keep any character a filesystem and the schema will take, which is
    every letter and digit rather than only the ASCII ones; and when the
    reduction is lossy — because characters were dropped, or because it came
    out empty — append a short digest of the original. Two different names
    then cannot collide, and a name that survives unchanged keeps the readable
    slug the schema asks for.
    """
    original = (name or "").strip()
    if not original:
        return ""
    # Canonical composition first. `Ünal` typed as one code point and `Ünal`
    # typed as `U` plus a combining diaeresis are the same name and the same
    # person; without this they are two pages, and which one you get depends
    # on which client the message came from.
    original = unicodedata.normalize("NFC", original)
    lowered = original.casefold()
    kept = "".join(c if (c.isalnum() or c == " ") else " " for c in lowered)
    cleaned = "_".join(kept.split())

    # Lossy in either direction: characters vanished, or separators that were
    # distinct in the original became the same one.
    faithful = cleaned == "_".join(lowered.split()) and cleaned != ""
    if faithful:
        return cleaned
    mark = hashlib.sha256(original.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}_{mark}" if cleaned else f"person_{mark}"


def existing_people() -> dict[str, str]:
    """Slug to the `last_interaction` its page records, for pages that have one.

    That date is what makes a quiet day quiet. Without it every correspondent
    above the threshold was offered on every tick, whether or not anything had
    happened since their page was written — so `wakeAgent` was never false and
    the idle-tick guarantee this recipe is built on did not hold for anybody
    with a page.
    """
    folder = memory_root() / "people"
    if not folder.is_dir():
        return {}
    found: dict[str, str] = {}
    for page in folder.glob("*.md"):
        try:
            head = page.read_text(encoding="utf-8")[:400]
        except OSError:
            # Unreadable means unknown, and unknown means offer the person
            # rather than skip them: a page nobody can read is one worth
            # looking at.
            found[page.stem] = ""
            continue
        seen = re.search(r"^last_interaction:\s*(\d{4}-\d{2}-\d{2})",
                         head, re.M)
        found[page.stem] = seen.group(1) if seen else ""
    return found


def stale_attention() -> list[dict[str, str]]:
    """Attention pages past their decay window, and pages that never existed.

    `current_priorities.md` is the one the ranking job gates on, so its absence
    is reported as loudly as its staleness. The repair job flags a stale page;
    it does not refresh one, because refreshing needs evidence it does not
    collect.
    """
    windows = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}
    folder = memory_root() / "attention"
    wanted = ("current_priorities", "active_threads")
    found = []
    today = datetime.now(timezone.utc).date()

    for name in wanted:
        path = folder / (name + ".md")
        if not path.exists():
            found.append({"page": name, "state": "missing"})
            continue
        try:
            head = path.read_text(encoding="utf-8")[:400]
        except OSError as exc:
            # Unreadable is a finding, not a crash. This job runs before the
            # repair job, so aborting here means the page nobody can read is
            # also the page nobody gets told about.
            found.append({"page": name, "state": "unreadable",
                          "detail": exc.strerror or str(exc)})
            continue
        updated = re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", head, re.M)
        decay = re.search(r"^decay:\s*(\w+)", head, re.M)
        if not updated:
            found.append({"page": name, "state": "no updated field"})
            continue
        try:
            written = datetime.strptime(updated.group(1), "%Y-%m-%d").date()
        except ValueError:
            # `2026-99-99` matches the shape and is not a date. Raising here
            # aborted the whole pass — including the report that would have
            # said which page was wrong.
            found.append({"page": name, "state": "unreadable date",
                          "updated": updated.group(1)})
            continue
        allowed = windows.get(decay.group(1) if decay else "weekly", 7)
        age = (today - written).days
        if age > allowed:
            found.append({"page": name, "state": "stale",
                          "updated": updated.group(1), "days_old": age})
    return found


def evidence(conn, since: str) -> dict[str, object]:
    """Who has been in touch, how often, and about what.

    Counting is done in SQL and the message text is truncated there too. That
    is not premature optimisation: an earlier version selected whole bodies and
    sorted on them, which made SQLite spill the sort to a temporary file. In a
    sandbox that cannot create one, that surfaces as `unable to open database
    file` — an error that reads like a permission or locking fault and is
    neither. A fixture-sized store never reaches the spill, so the bug is
    invisible until the first real mailbox. Keep the payload small here.
    """
    counted = conn.execute(
        "SELECT sender, COUNT(*), MAX(event_at) FROM items"
        "  WHERE event_at >= ? AND sender IS NOT NULL"
        "  GROUP BY sender", (since,)).fetchall()

    counts: Counter[str] = Counter()
    latest: dict[str, str] = {}
    for sender, count, last in counted:
        if AUTOMATED.search(sender or ""):
            continue
        counts[sender] = count
        latest[sender] = last

    have = existing_people()

    # Two different senders that reduce to one page name.
    #
    # A display name is not an identity: two people called `Sam Ruiz` share a
    # page, and the second overwrites the first's history under the first's
    # name. Neither is recoverable afterwards, because nothing in the store
    # distinguishes them — `items` keeps the display name and drops the
    # address and the Slack user id at normalization.
    #
    # So this fails closed. An ambiguous name is reported rather than written,
    # and the pass carries on with everybody else. Resolving it needs a stable
    # source identity in the store, which is a schema change and belongs with
    # the connectors that would populate it.
    by_slug: dict[str, set[str]] = {}
    for sender in counts:
        by_slug.setdefault(slug(sender), set()).add(sender)
    ambiguous = {mark: sorted(names) for mark, names in by_slug.items()
                 if mark and len(names) > 1}

    candidates = []
    for sender, count in counts.most_common():
        if count < PEOPLE_THRESHOLD:
            continue
        mark = slug(sender)
        if mark in ambiguous:
            continue
        last = (latest.get(sender) or "")[:10]
        if mark in have:
            # Offer an existing person only when something happened after
            # the date their page records. A page written last night and two
            # messages from last week is not work, and treating it as work
            # woke the agent on every run for the rest of the window — this
            # job runs nightly, so one quiet correspondent cost thirty model
            # calls to be told thirty times that nothing had changed.
            recorded = have[mark]
            if recorded and last and last <= recorded:
                continue
        candidates.append({
            "sender": sender,
            "slug": mark,
            "messages": count,
            "last_interaction": last,
            "has_page": mark in have,
            "page_records": have.get(mark) or None,
        })

    # A person with no page at all is more valuable than one whose page is
    # merely a few bullets behind, so they go first within the bound.
    candidates.sort(key=lambda c: (c["has_page"], -c["messages"]))
    chosen = candidates[:MAX_PEOPLE]
    wanted = {c["sender"] for c in chosen}

    interactions: dict[str, list[dict[str, str]]] = {}
    for sender in wanted:
        rows = conn.execute(
            "SELECT source, event_at, addressing,"
            "       substr(COALESCE(subject, body), 1, 200)"
            "  FROM items WHERE sender = ? AND event_at >= ?"
            "  ORDER BY event_at DESC LIMIT ?",
            (sender, since, MAX_INTERACTIONS)).fetchall()
        interactions[sender] = [
            {"when": (event_at or "")[:10], "source": source,
             "addressing": addressing, "text": " ".join((text or "").split())}
            for source, event_at, addressing, text in rows]

    return {"people": chosen, "interactions": interactions,
            "ambiguous_identity": ambiguous}


def open_obligations(conn) -> list[dict[str, object]]:
    """What the assistant currently believes is owed.

    Evidence for `active_threads.md` and nothing more. Rank, priority and
    title are judgments about what other people sent; none of them says the
    user chose anything, and `current_priorities.md` is not written from
    them — see `corrections()`.
    """
    rows = conn.execute(
        "SELECT global_rank, priority, title, source_id FROM obligations"
        " WHERE status='open' ORDER BY global_rank LIMIT 20").fetchall()
    return [{"rank": r[0], "priority": r[1], "title": r[2], "source_id": r[3]}
            for r in rows]


def corrections(conn, since: str) -> list[dict[str, object]]:
    """What the user themselves did, which is the only evidence of choosing.

    `current_priorities.md` is the page the ranking job gates its top tier on,
    and the bar for writing it is that the person chose the work. Nothing
    inbound clears that bar: a deadline somebody else set, an important
    sender, a busy thread — all of it is other people asking, however loudly,
    and the skill is right to refuse to promote any of it.

    The store does hold a trustworthy signal, and it is the one place the user
    writes rather than receives. `correct.py` is the only source of
    `actor='user'` events: raising something to `high` is the person saying
    this matters to them, and ignoring something is them saying it does not.
    Both are choices, made deliberately, recorded with their subject.

    Without this the job could only ever write an empty priorities page, and
    the ranking gate it exists to feed would stay shut on every install.
    """
    rows = conn.execute(
        "SELECT e.id, e.ts, e.event_type, e.after_json, o.title, o.source_id"
        "  FROM events e JOIN obligations o ON o.id = e.obligation_id"
        " WHERE e.actor = 'user' AND e.ts >= ?"
        " ORDER BY e.ts DESC LIMIT 40", (since,)).fetchall()

    out: list[dict[str, object]] = []
    for event_id, ts, event_type, after_json, title, source_id in rows:
        try:
            after = json.loads(after_json) if after_json else {}
        except (TypeError, json.JSONDecodeError):
            after = {}

        # The field `correct.py` actually writes. Reading `priority` returned
        # None for every real override, and the first test for this inserted a
        # synthetic `priority` key, so the mismatch was invisible from both
        # sides at once.
        tier = after.get("manual_priority")
        status = after.get("status")

        # A choice has a direction, and only one direction belongs on the
        # priorities page. Raising something to `high` is the person saying
        # this is their work. Setting it to `low`, or ignoring it, is them
        # saying it is not — evidence about them, and useful, but writing it
        # into `current_priorities.md` would promote exactly what they pushed
        # away.
        if tier == "high":
            direction = "chose"
        elif tier in ("medium", "low") or status == "ignored":
            direction = "declined"
        else:
            direction = "other"

        out.append({"event_id": event_id, "when": (ts or "")[:10],
                    "action": event_type, "title": title,
                    "source_id": source_id, "to": tier or status,
                    "direction": direction})
    return out


def applied_events(root) -> set[int]:
    """Event ids the priorities page already reflects.

    A correction is evidence once. Returning every event in the window on
    every pass woke the writer nightly for a month over one thing the user did
    once — the same defect as offering a correspondent whose page is already
    current, arriving from the other side.

    The record lives in the page itself rather than beside it. A marker file
    written after the page could be lost with the page still written, or
    written with the page still missing; a line in the page is durable exactly
    when the page is, which is the only moment that matters.
    """
    page = root / "attention" / "current_priorities.md"
    try:
        text = page.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {int(found) for found in re.findall(r"<!--\s*applied:\s*(\d+)\s*-->",
                                               text)}


def main() -> int:
    ensure_store()
    seeded = bootstrap(memory_root())
    window = bounded_days("MEMORY_WINDOW_DAYS", WINDOW_DAYS)
    since = (datetime.now(timezone.utc)
             - timedelta(days=window)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with write_txn() as conn:
        found = evidence(conn, since)
        obligations = open_obligations(conn)
        chosen = corrections(conn, since)

    # Everything the priorities page already accounts for. Still handed over,
    # because the page is rewritten whole and the model needs what is already
    # on it, but not counted as work.
    seen_events = applied_events(memory_root())
    unapplied = [c for c in chosen if c["event_id"] not in seen_events]

    report = {
        "window_days": window,
        "since": since,
        "people_threshold": PEOPLE_THRESHOLD,
        "memory_root": str(memory_root()),
        "seeded": seeded,
        "schema": str(memory_root().parent.parent / "schema.md"),
        "people": found["people"],
        # Named rather than silently skipped: somebody whose page is never
        # written should be able to find out why.
        "ambiguous_identity": found["ambiguous_identity"],
        "interactions": found["interactions"],
        "open_obligations": obligations,
        # Kept separate from `open_obligations` on purpose. One is what other
        # people asked for; this is what the user did about it. Only the
        # second may reach `current_priorities.md`.
        "user_corrections": chosen,
        "unapplied_corrections": unapplied,
        "attention": stale_attention(),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Nothing to write is the common case on a quiet day, and it must be free.
    # A missing or stale attention page counts as work even when no person
    # qualifies, because that page is what the ranking job gates on.
    work = (bool(found["people"]) or bool(report["attention"])
            or bool(unapplied))
    if not work:
        print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
