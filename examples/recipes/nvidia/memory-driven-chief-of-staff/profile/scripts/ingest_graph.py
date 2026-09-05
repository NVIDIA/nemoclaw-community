# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the user's own mail into the intake, through a credential it never
holds.

The counterpart to `ingest_slack.py`, and deliberately the same shape where
the two sources allow it: a bounded read, exit codes that say what went wrong,
and a credential that is a placeholder inside the sandbox. What this sees in
`MS_GRAPH_ACCESS_TOKEN` is `openshell:resolve:env:…`, sixty-odd bytes of
nothing; the OpenShell gateway substitutes the real delegated token at the
egress boundary and refreshes it on its own schedule. A compromised collector
leaks a string that is useless off this host.

Where the two sources differ is deletion, and the difference decides the
design. Slack offers no way to learn that a message was removed — its absence
from a bounded read cannot be told apart from it lying outside the window — so
Slack content ages out on the retention pass. Graph reports deletions
explicitly through the delta query, so this uses that rather than a time
filter, and a message deleted at the source is tombstoned and its body cleared
at once rather than a month later.

That choice has a second benefit worth naming, because it removes a whole
class of bug. A delta cursor is opaque and is only issued when a synchronisation
round completes. There is no way to construct one from a message this run
happened to see, so "only a complete crawl may advance the watermark" is
enforced by the protocol rather than by remembering to write it correctly.

    python3 ingest_graph.py            # incremental
    python3 ingest_graph.py --recheck  # re-probe the mailbox identity

Exit codes are the contract `select_intake.py` reads:

    0  collected, or never configured
    1  something else went wrong
    2  the credential is missing, wrong, or refused
    3  rate limited before the work finished
    4  the token works but lacks the scope this needs
"""

from __future__ import annotations

import json
import sqlite3
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from _db import ensure_store, ledger_path, write_txn
from normalize import graph_message_to_item, insert_items

API = "https://graph.microsoft.com/v1.0"

EXIT_OK = 0
EXIT_OTHER = 1
EXIT_CREDENTIAL = 2
EXIT_RATE_LIMIT = 3
EXIT_SCOPE = 4

# How far back the first synchronisation reaches.
#
# The delta query accepts a `receivedDateTime` filter on the initial request,
# so this is a real choice rather than all-or-nothing — measured against the
# live service, not assumed. Seven days is the default because it produces a
# useful inbox on the first tick instead of a month of archaeology, and
# `GRAPH_BACKFILL_DAYS` moves it.
#
# What it does *not* do is bound what comes later. The delta cursor the first
# round issues carries no filter, so once the baseline exists every change in
# the folder is reported — including an older message being deleted. Choosing
# seven days is choosing where to start, not choosing to be told less
# afterwards.
BACKFILL_DAYS = 7
MAX_BACKFILL_DAYS = 3650

# Requests per run.
#
# A first synchronisation over a wide window can need many more pages than one
# tick should spend, so it is resumable: the page link is kept and the next
# tick continues from it. The bound exists because a scheduled job that can
# issue unbounded requests will eventually meet a mailbox that makes it do so,
# and the tick after that one still has to finish.
REQUEST_BUDGET = 10


# How long one run may spend being told to wait.
#
# Graph answers 429 with a `Retry-After`, and a caller that honours it without
# a total bound will honour it forever: the page budget counts successful
# responses, and a scheduled pre-step has no timeout of its own. Reproduced at
# review: 9,248 retries and still going. A tick that cannot make progress
# inside this budget reports rate limiting and lets the next one try.
MAX_TOTAL_BACKOFF_SECONDS = 120
PAGE_SIZE = 50
MAX_BACKOFF_SECONDS = 30

# Where the synchronisation stands. Not in `cursors`, because that table holds
# one opaque string per scope and this needs two states — mid-round and
# between rounds — plus the mailbox identity.
STATE_FILE = "graph_state.json"

FIELDS = ("id,parentFolderId,conversationId,receivedDateTime,from,subject,"
          "body,webLink,isRead,toRecipients,ccRecipients,"
          "internetMessageId")


class GraphError(Exception):
    """A failure with a class attached, so the exit code is not a guess."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def classify_token(raw: str | None) -> str:
    """What kind of thing is in the variable.

    The placeholder is the expected case and the only one this recipe is built
    around. A real bearer token appearing here means somebody put a live
    credential in the sandbox by hand, which works but is the arrangement this
    design exists to avoid — so it runs, and says so once.
    """
    if raw is None or not raw.strip():
        return "absent"
    token = raw.strip()
    if token.startswith("openshell:resolve:"):
        return "placeholder"
    if token.count(".") == 2 and token.startswith("ey"):
        return "bearer"
    return "unrecognised"


def bounded_days(name: str, default: int) -> int:
    """Read a positive, bounded day count from the environment.

    Same shape and same reasons as the other bounded settings here: a zero
    window synchronises nothing while reporting a clean run, and a negative one
    puts the start in the future so the filter excludes everything. Both are
    mistakes only noticed by their consequences.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"{name} must be a whole number of days between 1 and "
            f"{MAX_BACKFILL_DAYS}; got {raw!r}")
    if value < 1 or value > MAX_BACKFILL_DAYS:
        raise SystemExit(
            f"{name} must be between 1 and {MAX_BACKFILL_DAYS}; got {value}")
    return value


def state_path():
    return ledger_path().parent.parent / STATE_FILE


def read_state() -> dict[str, Any]:
    try:
        found = json.loads(state_path().read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        # Losing this costs a re-synchronisation, not correctness: without it
        # the next run starts a fresh delta round and the rows are idempotent
        # on `source_id`.
        pass


class Budget:
    """How long one tick may spend waiting, across every request it makes.

    The bound belongs to the tick, not to the request. Held per request it
    multiplies by however many requests the tick makes — a page budget of ten
    turned a 120-second ceiling into twenty minutes of a scheduled job sitting
    in `sleep`, which is not a bound anybody set and not one anybody would see
    until it happened.

    Passed explicitly rather than defaulted, so a call site that forgets it is
    a `TypeError` here rather than a request quietly given a budget of its
    own — which is the defect this replaces.
    """

    def __init__(self, seconds: float | None = None):
        # Read at construction, not bound as a default argument: a default is
        # evaluated once at import, so a test or an operator changing the
        # constant afterwards would be silently ignored.
        self.limit = (MAX_TOTAL_BACKOFF_SECONDS if seconds is None
                      else seconds)
        self.waited = 0.0

    def spend(self, wait: float) -> None:
        """Wait, or refuse because this tick has waited enough already.

        Refusing is not failing: the cursor is not advanced, so the next tick
        continues from the same place. A rate limit is the service asking for
        patience on a timescale longer than one tick, and the answer to it is
        to come back later rather than to hold the job open.
        """
        if self.waited + wait > self.limit:
            raise GraphError(
                "rate limited for longer than one tick may wait "
                f"({int(self.waited)}s so far); the next tick continues "
                "from where this one stopped", "rate_limit")
        time.sleep(wait)
        self.waited += wait


def call(path: str, token: str, budget: Budget, *,
         absolute: bool = False) -> dict[str, Any]:
    """One Graph GET, with the failures that need distinguishing.

    A 401 or 403 is the credential; a 429 is the service asking for patience;
    a 410 means the delta cursor has expired and the round must start again.
    Everything else is lumped together, because a collector that tries to
    interpret Graph's full error surface will be wrong about it.
    """
    url = path if absolute else API + path
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        # Ask for a plain-text body. Graph honours this per request; without
        # it every message arrives as HTML, and the store would hold several
        # kilobytes of layout for the sake of a paragraph.
        "Prefer": 'outlook.body-content-type="text"',
    })
    delay = 1.0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise GraphError(
                    "Microsoft Graph refused the credential (HTTP %d)." %
                    exc.code,
                    "credential") from exc
            if exc.code == 410:
                raise GraphError("delta cursor expired", "resync") from exc
            if exc.code == 429:
                retry = exc.headers.get("Retry-After")
                wait = float(retry) if retry and retry.isdigit() else delay
                if wait > MAX_BACKOFF_SECONDS:
                    raise GraphError("rate limited beyond the backoff bound",
                                     "rate_limit") from exc
                budget.spend(wait)
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
                continue
            raise GraphError("Graph returned HTTP %d" % exc.code) from exc
        except urllib.error.URLError as exc:
            # The egress boundary refuses a host it does not allow with a
            # tunnel error, indistinguishable here from the network being
            # down — and the operator's next step is the same either way.
            raise GraphError("could not reach graph.microsoft.com",
                             "other") from exc


def identity(token: str, state: dict[str, Any],
             budget: Budget) -> tuple[dict[str, Any], bool]:
    """Whose mailbox this is, checked every run. Returns it and whether it
    changed.

    Not cached against the credential, which was the mistake here. Inside the
    sandbox the credential is a placeholder that the gateway substitutes, and
    the placeholder does not change when the token behind it is replaced — so
    a digest of it stays the same across a re-authorisation to a completely
    different account. The identity cache and the delta cursor would then be
    carried over to somebody else's mailbox, which is the one outcome worth
    spending a request per tick to prevent.

    So `/me` is asked every run, and what is compared is the mailbox address
    — a durable identifier belonging to the account rather than to the
    credential presented for it. One request against a bounded budget, and
    the answer is the addressing input every message needs anyway.
    """
    me = call("/me?$select=mail,userPrincipalName,displayName", token,
              budget)
    address = me.get("mail") or me.get("userPrincipalName") or ""
    if not address:
        raise GraphError(
            "The token works but the mailbox has no address. This usually "
            "means an application token rather than a delegated one; this "
            "recipe needs delegated Mail.Read and User.Read.", "scope")

    previous = state.get("identity")
    changed = bool(isinstance(previous, dict)
                   and previous.get("address")
                   and previous["address"].lower() != address.lower())
    return ({"address": address, "display_name": me.get("displayName")},
            changed)


def first_round_url(days: int) -> str:
    """The initial delta request, bounded to a window the user chose."""
    start = (datetime.now(timezone.utc)
             - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = urllib.parse.urlencode({
        "$select": FIELDS,
        "$top": PAGE_SIZE,
        "$filter": "receivedDateTime ge %s" % start,
    })
    return "/me/mailFolders/inbox/messages/delta?" + query


def still_in_mailbox(source_id: str, token: str, budget: Budget) -> str:
    """Is this message somewhere else in the mailbox, gone, or unanswerable?

    Three answers, not two. A bool had to spend "I could not find out" on one
    of the other two, and both were wrong: as "gone" it cleared the body of a
    message that had merely been filed away, and as "present" it let a real
    deletion pass unrecorded.

    Asked by `internetMessageId`, which a message keeps when it moves; the
    per-folder id does not, so it cannot be used here.

    A failure to answer stops the round. Reading it as "still there" looked
    like the safe direction — a body kept a little longer against a body
    cleared because a search timed out — but "a little longer" was wrong. The
    removal is only reported once. Treat it as a move and the round finishes,
    the cursor advances past the page that carried it, and nothing ever asks
    again: the message stays in the store as though it were never deleted,
    permanently, and the person who deleted it is never told otherwise.

    Stopping costs a re-read of pages this tick already handled, which is
    idempotent, and the next tick asks the question again.
    """
    with sqlite3.connect(ledger_path()) as conn:
        row = conn.execute(
            "SELECT internet_message_id FROM items WHERE source_id = ?",
            (source_id,)).fetchone()
    internet_id = row[0] if row else None
    if not internet_id:
        # Nothing to ask about: a row collected before this column existed,
        # or a message that arrived without the field. Unknown, and unknown
        # is not "deleted" — reading it that way tombstoned the row and
        # cleared its body, which is the irreversible direction and was
        # reached without contacting Graph at all.
        return "unknown"
    query = urllib.parse.quote(
        "internetMessageId eq '%s'" % internet_id.replace("'", "''"), safe="")
    try:
        found = call("/me/messages?$filter=%s&$select=id&$top=1" % query,
                     token, budget)
    except GraphError as exc:
        # The class is carried through so the exit code still says whether
        # this was the credential, a rate limit, or something else.
        raise GraphError(
            "could not establish whether a removed message was deleted or "
            f"moved ({exc}); the round stops here rather than advancing past "
            "a removal it did not resolve", exc.kind) from exc
    return "present" if found.get("value") else "gone"


def tombstone(conn, source_ids: list[str]) -> int:
    """Record that the source removed these, and drop their text now.

    Not a DELETE. Obligations and events hang off `source_id`, so removing the
    row would break the audit trail that explains why something was ranked or
    ignored — the record of a decision outliving its subject is the point.
    What goes is the content, immediately rather than at the next retention
    pass, because somebody who deleted a message has said what they want.

    `deleted_at` and `body_cleared_at` are both set and mean different things:
    one is the person deleting, the other is this recipe ageing text out on
    its own schedule. A report that conflated them would answer the wrong
    question.
    """
    if not source_ids:
        return 0
    marks = ",".join("?" * len(source_ids))
    cursor = conn.execute(
        "UPDATE items"
        "   SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
        "       body = NULL,"
        "       body_cleared_at = COALESCE(body_cleared_at,"
        " strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
        f" WHERE source_id IN ({marks}) AND deleted_at IS NULL",
        source_ids)
    return cursor.rowcount


def commit_rows(items: list[dict[str, Any]]) -> int:
    """The page's messages, in their own transaction.

    Separate from the tombstones, and before them, for two reasons. A write
    transaction held across a network call holds a write lock for the length
    of that call, and the user's own corrections queue behind it. And the
    question a removal asks — what is this message's own identity — is
    answered from the row, so the rows have to be there before it is asked;
    a message collected in one page and removed in a later page of the same
    round is otherwise unanswerable.

    The delta cursor is saved by the caller and only after this returns: a
    cursor recorded over rows that were never written would have the next
    round start past them.
    """
    if not items:
        return 0
    with write_txn() as conn:
        return insert_items(conn, items)


def commit_tombstones(removed: list[str]) -> int:
    """What the source no longer has, once that has actually been asked."""
    if not removed:
        return 0
    with write_txn() as conn:
        return tombstone(conn, removed)


def collect(token: str, address: str, state: dict[str, Any],
            days: int, budget: Budget) -> dict[str, Any]:
    """One synchronisation round, or as much of one as the budget allows.

    Three states, and which one this run is in decides where it starts:

    - no cursor at all: begin a round, bounded to the chosen window
    - `next`: a round was interrupted by the budget, continue from that page
    - `delta`: a round completed, ask what has changed since

    Only a completed round yields a new delta cursor, and one cannot be
    fabricated from the messages this run happened to see. The rule that a
    partial crawl must not advance the watermark is therefore enforced by the
    protocol rather than by this code remembering it.
    """
    resuming = bool(state.get("next"))
    if state.get("next"):
        url, absolute = state["next"], True
    elif state.get("delta"):
        url, absolute = state["delta"], True
    else:
        url, absolute = first_round_url(days), False

    added_total = removed_total = moved = unresolved = pages = 0
    delta_link = None

    while url and pages < REQUEST_BUDGET:
        payload = call(url, token, budget, absolute=absolute)
        pages += 1

        batch = payload.get("value") or []
        # A delta page mixes changes and removals, and the removals need a
        # second question asked before any of them is believed.
        #
        # Graph reports `@removed.reason == "deleted"` when a message leaves
        # the folder being tracked — whether it was deleted or filed
        # somewhere else. An earlier version of this read a `"changed"`
        # reason for a move; no such value is documented and the service does
        # not send one, so archiving a message was recorded as the person
        # deleting it and its body was cleared. Measured against the live
        # service: moving a message to Archive produces exactly the removal a
        # deletion produces, and the per-folder id changes, so the id cannot
        # answer it either.
        #
        # What survives a move is `internetMessageId`, which is the message's
        # own identity rather than its position. If a search of the mailbox
        # still finds it, it moved; if it does not, it is gone. One request
        # per removal, and removals are rare beside messages.
        #
        # That identity is kept on the row, by `normalize`, rather than in a
        # map beside the cursor. The map was bounded at five thousand and
        # evicted oldest-first, so filing away a message older than that
        # produced a removal nobody could ask about — and the code read the
        # absence as a deletion, cleared the body, and never made a request.
        # The row is where the message already is, and it does not evict.
        gone_ids = [m["id"] for m in batch
                    if isinstance(m.get("@removed"), dict) and m.get("id")]
        present = [m for m in batch if "@removed" not in m and m.get("id")]

        # Written before the removals are resolved, so a message collected
        # earlier in this same round can be asked about in a later page.
        items = [graph_message_to_item(m, address) for m in present]
        added_total += commit_rows(items)

        verdicts = {source_id: still_in_mailbox(source_id, token, budget)
                    for source_id in gone_ids}
        moved += sum(1 for v in verdicts.values() if v == "present")
        unresolved += sum(1 for v in verdicts.values() if v == "unknown")
        removed_total += commit_tombstones(
            [s for s, verdict in verdicts.items() if verdict == "gone"])

        delta_link = payload.get("@odata.deltaLink")
        url = payload.get("@odata.nextLink")
        absolute = True

    # Save exactly one of the two, and only what the round actually reached.
    if delta_link:
        state.pop("next", None)
        state["delta"] = delta_link
        complete = True
    elif url:
        state["next"] = url
        complete = False
    else:
        # No further page and no delta cursor: Graph gave neither, so the round
        # is not finished and there is nothing to resume from. Start again next
        # tick rather than recording a position that does not exist.
        state.pop("next", None)
        complete = False

    return {"source": "email", "scope": "inbox", "added": added_total,
            "removed": removed_total, "moved": moved,
            # Removals that left the folder while the row had no identity of
            # its own to ask about — collected before the column existed, or
            # arrived without the field. Left alone rather than tombstoned,
            # and counted rather than passed over in silence, because the
            # alternative was clearing the body of a message that had only
            # been filed away.
            "unresolved_removals": unresolved,
            "pages": pages,
            "resumed": resuming, "complete": complete,
            "synchronised": bool(state.get("delta"))}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    refresh = "--recheck" in args

    raw = os.environ.get("MS_GRAPH_ACCESS_TOKEN")
    kind = classify_token(raw)

    ensure_store()
    state = read_state()

    # Never configured is not the same as broken, and the difference decides
    # whether every idle tick wakes the model. This file exists as soon as the
    # recipe is installed, long before most people connect a mailbox — so an
    # absent credential has to be free, or the wake gate never fires again.
    #
    # The hole is a credential that *disappears*: a detached provider empties
    # the variable, which then looks like "never set up". The saved state
    # closes it, because it is only written after a mailbox answered once.
    if kind == "absent":
        if state:
            print("Mail was connected and MS_GRAPH_ACCESS_TOKEN has gone. If "
                  "this sandbox uses an OpenShell provider, check it is still "
                  "attached: openshell sandbox provider list <sandbox>.",
                  file=sys.stderr)
            return EXIT_CREDENTIAL
        print(json.dumps({"unconfigured": True}))
        return EXIT_OK

    if kind == "unrecognised":
        print("MS_GRAPH_ACCESS_TOKEN holds something that is neither an "
              "OpenShell placeholder nor a bearer token. Expected the gateway "
              "to inject `openshell:resolve:env:…`.", file=sys.stderr)
        return EXIT_CREDENTIAL

    token = (raw or "").strip()
    days = bounded_days("GRAPH_BACKFILL_DAYS", BACKFILL_DAYS)

    # One budget for the whole tick, shared by every request it makes —
    # the identity check, both rounds if the cursor expired, and every
    # removal lookup in between.
    budget = Budget()

    try:
        who, mailbox_changed = identity(token, state, budget)
        if mailbox_changed:
            # A different account. Everything remembered describes the old
            # one: a delta cursor issued for its inbox, a resume link into
            # its pages, identities of its messages. Carrying any of it over
            # would synchronise one mailbox against another's position.
            print("the mailbox has changed; discarding the previous "
                  "synchronisation state", file=sys.stderr)
            for key in ("delta", "next"):
                state.pop(key, None)
        elif refresh:
            state.pop("delta", None)
            state.pop("next", None)
        state["identity"] = who
        try:
            report = collect(token, who["address"], state, days,
                             budget)
        except GraphError as exc:
            if exc.kind != "resync":
                raise
            # Graph expires a delta cursor that has gone unused for too long.
            # Recovering means a fresh round over the window; the rows are
            # idempotent on `source_id`, so re-reading costs requests rather
            # than duplicates.
            print("delta cursor expired; starting a new synchronisation round",
                  file=sys.stderr)
            state.pop("delta", None)
            state.pop("next", None)
            report = collect(token, who["address"], state, days,
                             budget)
            report["resynchronised"] = True
    except GraphError as exc:
        print(str(exc), file=sys.stderr)
        return {"credential": EXIT_CREDENTIAL, "rate_limit": EXIT_RATE_LIMIT,
                "scope": EXIT_SCOPE}.get(exc.kind, EXIT_OTHER)

    # After the rows, never before: a cursor saved over rows that were not
    # written would have the next round start past them.
    save_state(state)

    report["backfill_days"] = days
    print(json.dumps(report))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
