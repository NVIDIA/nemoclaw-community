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

import identity
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

# How many corrections one pass carries. Unapplied ones are never the part
# dropped, so a bound cannot lose a choice that has not been written up yet.
MAX_CORRECTIONS = 40
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


def page_names(display: dict[object, str],
               have: dict[str, dict[str, object]],
               members: dict[object, list[object]]) -> dict[object, str]:
    """Person -> the page slug that person owns.

    Two people called `Sam Ruiz` need two pages, and each needs to keep its
    own name across runs. Neither follows from the display name, so the
    allocation is driven by identity and by what the pages on disk claim:

    - A page that records **any** of this person's identities keeps its name.
      That is what makes the name durable, and why it is a list: a colleague
      whose Slack account is later confirmed to be the same person as their
      mailbox must not be moved to a new page because the identity the page
      happens to be found by was not the one that wrote this week.
    - Otherwise the readable slug is used when exactly one person wants it
      and no other person already holds it.
    - Otherwise every contender takes a digest of its own identity. Nobody
      wins the readable name by being processed first, because a winner
      picked that way changes between runs, and a page name that changes is
      a page lost.

    A page claiming no identity at all was written before the field existed.
    It is treated as belonging to the sole contender for its name — the
    migration case, and the alternative is abandoning a real page and
    starting a blank one beside it. With two contenders it cannot be
    attributed to either, so both take digests and the old page is left where
    it is.
    """
    # Identity text -> the page that claims it. A page may claim several.
    claimed: dict[str, str] = {}
    for mark, page in have.items():
        for text in page.get("identities") or []:
            claimed.setdefault(text, mark)

    names: dict[object, str] = {}
    for person in display:
        for who in members.get(person, [person]):
            if str(who) in claimed:
                names[person] = claimed[str(who)]
                break

    contenders: dict[str, list[object]] = {}
    for person in display:
        if person in names:
            continue
        contenders.setdefault(slug(display[person]), []).append(person)

    for base, people in contenders.items():
        if not base:
            base = "person"
        # Sorted so the digest set is the same whatever order the store
        # returned the senders in.
        for person in sorted(people, key=str):
            solo = len(people) == 1 and (
                base not in have or not (have[base].get("identities") or []))
            names[person] = base if solo else (
                f"{base}_{hashlib.sha256(str(person).encode()).hexdigest()[:8]}")
    return names


def existing_people() -> dict[str, dict[str, str]]:
    """Page slug to what that page records about who it is about, and when.

    `last_interaction` is what makes a quiet day quiet. Without it every
    correspondent above the threshold was offered on every tick, whether or
    not anything had happened since their page was written — so `wakeAgent`
    was never false and the idle-tick guarantee this recipe is built on did
    not hold for anybody with a page.

    `source_key` is what lets a page keep its name. It is the stable identity
    the page was written about; pages written before the field existed have
    none, which is a fact `page_names` needs and cannot get any other way.
    """
    folder = memory_root() / "people"
    if not folder.is_dir():
        return {}
    found: dict[str, dict[str, str]] = {}
    for page in folder.glob("*.md"):
        try:
            head = page.read_text(encoding="utf-8")[:400]
        except OSError:
            # Unreadable means unknown, and unknown means offer the person
            # rather than skip them: a page nobody can read is one worth
            # looking at.
            found[page.stem] = {"last_interaction": "", "source_key": ""}
            continue
        seen = re.search(r"^last_interaction:\s*(\d{4}-\d{2}-\d{2})",
                         head, re.M)
        found[page.stem] = {
            "last_interaction": seen.group(1) if seen else "",
            "identities": _page_identities(head),
        }
    return found


def _page_identities(head: str) -> list[str]:
    """Every identity a page claims, from either spelling of the field.

    `identities:` is a YAML list — a person holds as many as they have places
    to write from, and privileging one of them as `source_key` made "which is
    the primary" a question with no answer as soon as a third arrived. Pages
    written before the list existed carry the single `source_key:`, which is
    read as a list of one rather than migrated: the page is the user's, and
    rewriting their frontmatter to suit a schema change is not this job's.
    """
    listed = re.search(r"^identities:\s*\n((?:\s*-\s*\S+\s*\n)+)",
                       head, re.M)
    if listed:
        return [line.strip().lstrip("-").strip()
                for line in listed.group(1).splitlines() if line.strip()]
    single = re.search(r"^source_key:\s*(\S+)", head, re.M)
    return [single.group(1)] if single else []


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
    # Grouped by identity and display name together, so a person who changed
    # how their name is shown is still one person, and two people who share a
    # display name are still two.
    #
    # Only rows that carry an identity. Falling back to the display name for
    # the ones that do not looked harmless and split people in half: a store
    # upgraded to v3 keeps `sender_key IS NULL` on everything collected
    # before, so one real correspondent appeared twice — once keyed by their
    # name, from the old rows, and once by their address, from the new ones —
    # and got two pages that each held half their history. A display name is
    # not an identity in the fallback either.
    #
    # Grouped by `(source, sender_key)`, not by the key alone. Two sources can
    # mint the same string, and merging two people because their opaque ids
    # happened to match would be silent and unrecoverable.
    counted = conn.execute(
        "SELECT source, sender_key, sender, sender_handle,"
        "       COUNT(*), MAX(event_at)"
        "  FROM items"
        "  WHERE event_at >= ? AND sender IS NOT NULL AND sender_key IS NOT NULL"
        "  GROUP BY source, sender_key, sender, sender_handle",
        (since,)).fetchall()

    # Said out loud rather than silently skipped. These are rows from before
    # the upgrade; they stop appearing as the collectors re-read their window
    # and `insert_items` fills the identity in, and they are gone entirely
    # once the window has turned over.
    unkeyed = conn.execute(
        "SELECT COUNT(*) FROM items"
        "  WHERE event_at >= ? AND sender IS NOT NULL AND sender_key IS NULL",
        (since,)).fetchone()[0]

    # Per identity first: how much they wrote, when last, and what they are
    # called and known as there.
    seen: Counter[identity.Identity] = Counter()
    last_at: dict[identity.Identity, str] = {}
    shown: dict[identity.Identity, str] = {}
    handles: dict[identity.Identity, str | None] = {}
    for source, key, sender, handle, count, last in counted:
        if AUTOMATED.search(sender or ""):
            continue
        if not key or not source:
            continue
        who = identity.Identity(source, key)
        seen[who] += count
        handles.setdefault(who, handle)
        if last and last > last_at.get(who, ""):
            last_at[who] = last
            # The name they go by now, not the one they used first.
            shown[who] = sender
        shown.setdefault(who, sender)

    # Then per person: identities the user has confirmed belong together are
    # one correspondent with one page, however many of them there are.
    persons = identity.resolve(conn, seen)
    counts: Counter[identity.Identity] = Counter()
    latest: dict[identity.Identity, str] = {}
    display: dict[identity.Identity, str] = {}
    members: dict[identity.Identity, list[identity.Identity]] = {}
    for who, count in seen.items():
        person = persons.of(who)
        counts[person] += count
        members.setdefault(person, persons.group(who))
        if last_at.get(who, "") > latest.get(person, ""):
            latest[person] = last_at[who]
            display[person] = shown[who]
        display.setdefault(person, shown[who])

    have = existing_people()
    today = datetime.now(timezone.utc).date().isoformat()

    names = page_names(display, have, members)

    # Namesakes still worth reporting: two people the agent cannot tell apart
    # by name get one page each, and it should say so on both rather than
    # leave a reader to guess which colleague a page is about.
    by_name: dict[str, set[identity.Identity]] = {}
    for person, sender in display.items():
        by_name.setdefault(sender, set()).add(person)
    shared = {sender: sorted(names[p] for p in people)
              for sender, people in by_name.items() if len(people) > 1}

    # Identities that may be one person, for the user to answer later. The
    # job does not wait for the answer and does not act without one.
    proposals = identity.candidates(
        [(who, shown.get(who, ""), handles.get(who)) for who in seen],
        identity.decisions(conn), persons)

    candidates = []
    group_of: dict[str, list[identity.Identity]] = {}
    for key, count in counts.most_common():
        if count < PEOPLE_THRESHOLD:
            continue
        sender = display[key]
        mark = names[key]
        last = (latest.get(key) or "")[:10]
        if mark in have:
            # Offer an existing person only when something happened after
            # the date their page records. A page written last night and two
            # messages from last week is not work, and treating it as work
            # woke the agent on every run for the rest of the window — this
            # job runs nightly, so one quiet correspondent cost thirty model
            # calls to be told thirty times that nothing had changed.
            recorded = have[mark]["last_interaction"]
            # A page dated in the future would skip that person for as long as
            # the date stood — silently, and a typo or a clock skew is enough
            # to write one. Treat it as unknown, which means look.
            if recorded > today:
                recorded = ""
            if recorded and last and last <= recorded:
                continue
        candidates.append({
            "sender": sender,
            # Every identity this person writes from, not one of them. The
            # page records the whole list, so it is still found when the
            # message that arrives next comes from a different source.
            "identities": [str(i) for i in members[key]],
            "slug": mark,
            "messages": count,
            "last_interaction": last,
            "has_page": mark in have,
            "page_records": (have[mark]["last_interaction"] or None)
                            if mark in have else None,
        })
        group_of[mark] = members[key]

    # A person with no page at all is more valuable than one whose page is
    # merely a few bullets behind, so they go first within the bound.
    candidates.sort(key=lambda c: (c["has_page"], -c["messages"]))
    chosen = candidates[:MAX_PEOPLE]
    wanted = [(c["slug"], group_of[c["slug"]]) for c in chosen]

    # Keyed by page slug, not by display name: two namesakes would otherwise
    # write into one entry and the second would replace the first's history.
    interactions: dict[str, list[dict[str, str]]] = {}
    for mark, group in wanted:
        # One query per identity rather than a join or an IN list built from
        # two columns: the store keeps its tables as independent silos and
        # the number of identities a person has is small.
        rows: list[tuple] = []
        for who in group:
            rows += conn.execute(
                "SELECT source, event_at, addressing,"
                "       substr(COALESCE(subject, body), 1, 200)"
                "  FROM items WHERE source = ? AND sender_key = ?"
                "    AND event_at >= ?"
                "  ORDER BY event_at DESC LIMIT ?",
                (who.source, who.key, since, MAX_INTERACTIONS)).fetchall()
        rows.sort(key=lambda r: r[1] or "", reverse=True)
        interactions[mark] = [
            {"when": (event_at or "")[:10], "source": source,
             "addressing": addressing, "text": " ".join((text or "").split())}
            for source, event_at, addressing, text in rows[:MAX_INTERACTIONS]]

    return {"people": chosen, "interactions": interactions,
            "shared_display_name": shared,
            "identity_candidates": proposals,
            "identity_conflicts": identity.contradictions(conn),
            "messages_without_identity": unkeyed}


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
    # No LIMIT here, and the bound is applied after the classification below.
    #
    # Taking the newest forty in SQL dropped the oldest silently, and the ones
    # dropped were exactly the ones most likely to be unapplied — an older
    # correction that had never been written up could be pushed out of the
    # window forever by newer traffic. A choice the person made deliberately
    # would vanish without anything saying so.
    rows = conn.execute(
        "SELECT e.id, e.ts, e.event_type, e.after_json, o.title, o.source_id"
        "  FROM events e JOIN obligations o ON o.id = e.obligation_id"
        " WHERE e.actor = 'user' AND e.ts >= ?"
        " ORDER BY e.ts DESC", (since,)).fetchall()

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
        # priorities page.
        #
        # `correct.py` emits exactly three user events and all three are
        # classified here.
        #
        # Only an explicit `high` override is choosing. Raising something to
        # the top tier is the person saying it is their work, and nothing else
        # says that. Restoring an ignored obligation was briefly treated the
        # same way, on the reasoning that changing one's mind is a choice —
        # but the sequence `low` then `ignore` then `restore` leaves the
        # obligation at `low`, and reading the restore as `chose` would
        # promote work the person had deliberately kept down. Restoring means
        # track this again; it does not establish priority.
        #
        # Setting a lower tier or ignoring is `declined` — real evidence,
        # worth knowing, and the opposite of a priority.
        #
        # A restore is `other`: neither, and not guessed at. So are the event
        # types the schema allows that no user path writes today (`snoozed`,
        # `completed`); assuming a direction for one would be inventing intent
        # from a row somebody else's code might write later.
        if tier == "high":
            direction = "chose"
        elif tier in ("medium", "low") or event_type == "ignored":
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

    # Bound the payload, unapplied first.
    #
    # This is a batch, not a guarantee that everything unapplied is present:
    # with more unapplied corrections than the bound, the remainder waits for
    # a later pass — and gets there, because acknowledging this batch's
    # markers moves those events out of the way and the next pass takes the
    # next slice. What must not happen is the bound silently favouring
    # applied ones, so unapplied come first, and what was left out is
    # counted rather than omitted in silence.
    ordered = unapplied + [c for c in chosen if c["event_id"] in seen_events]
    dropped = max(0, len(ordered) - MAX_CORRECTIONS)
    chosen = ordered[:MAX_CORRECTIONS]
    unapplied = [c for c in chosen if c["event_id"] not in seen_events]

    report = {
        "window_days": window,
        "since": since,
        "people_threshold": PEOPLE_THRESHOLD,
        "memory_root": str(memory_root()),
        "seeded": seeded,
        "schema": str(memory_root().parent.parent / "schema.md"),
        "people": found["people"],
        # Namesakes get one page each, but the agent cannot tell them apart
        # by name and should say which page is about whom.
        "shared_display_name": found["shared_display_name"],
        # Identities that may be one person. Proposed, never acted on: the
        # user answers these after the run, and the run does not wait.
        "identity_candidates": found["identity_candidates"],
        # Answers that no longer agree with each other. Reported rather than
        # resolved, because neither side is knowably the wrong one.
        "identity_conflicts": found["identity_conflicts"],
        # Collected before the store kept identities. Not attributed to
        # anybody, because the only thing left to attribute them by is the
        # display name that cannot identify anybody.
        "messages_without_identity": found["messages_without_identity"],
        "interactions": found["interactions"],
        "open_obligations": obligations,
        # Kept separate from `open_obligations` on purpose. One is what other
        # people asked for; this is what the user did about it. Only the
        # second may reach `current_priorities.md`.
        "user_corrections": chosen,
        "unapplied_corrections": unapplied,
        "corrections_not_shown": dropped,
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
