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

import hashlib
import json
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
PAGE_SIZE = 50
MAX_BACKOFF_SECONDS = 30

# Where the synchronisation stands. Not in `cursors`, because that table holds
# one opaque string per scope and this needs two states — mid-round and
# between rounds — plus the mailbox identity.
STATE_FILE = "graph_state.json"

FIELDS = ("id,parentFolderId,conversationId,receivedDateTime,from,subject,"
          "body,webLink,isRead,toRecipients,ccRecipients")


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


def fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def call(path: str, token: str, *, absolute: bool = False) -> dict[str, Any]:
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
                time.sleep(wait)
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
                continue
            raise GraphError("Graph returned HTTP %d" % exc.code) from exc
        except urllib.error.URLError as exc:
            # The egress boundary refuses a host it does not allow with a
            # tunnel error, indistinguishable here from the network being
            # down — and the operator's next step is the same either way.
            raise GraphError("could not reach graph.microsoft.com",
                             "other") from exc


def identity(token: str, state: dict[str, Any], *,
             refresh: bool = False) -> dict[str, Any]:
    """Whose mailbox this is, cached.

    The address decides addressing — being a To recipient is being asked,
    being copied is being informed — so it is needed on every message and
    fetched once. Keyed on the credential, so replacing the token re-probes
    rather than inheriting the previous mailbox's identity along with its
    delta cursor.
    """
    mark = fingerprint(token)
    cached = state.get("identity")
    if not refresh and isinstance(cached, dict) and cached.get("token") == mark:
        return cached

    me = call("/me?$select=mail,userPrincipalName,displayName", token)
    address = me.get("mail") or me.get("userPrincipalName") or ""
    if not address:
        raise GraphError(
            "The token works but the mailbox has no address. This usually "
            "means an application token rather than a delegated one; this "
            "recipe needs delegated Mail.Read.", "scope")
    return {"token": mark, "address": address,
            "display_name": me.get("displayName")}


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


def commit(items: list[dict[str, Any]], removed: list[str]) -> tuple[int, int]:
    """Rows and tombstones, in one transaction, taken after the fetch.

    Holding a write transaction open across a network call holds a write lock
    for the length of that call, and the user's own corrections queue behind
    it. The delta cursor is saved by the caller and only after this returns:
    a cursor recorded over rows that were never written would have the next
    round start past them.
    """
    with write_txn() as conn:
        added = insert_items(conn, items) if items else 0
        gone = tombstone(conn, removed)
    return added, gone


def collect(token: str, address: str, state: dict[str, Any],
            days: int) -> dict[str, Any]:
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

    added_total = removed_total = pages = 0
    delta_link = None

    while url and pages < REQUEST_BUDGET:
        payload = call(url, token, absolute=absolute)
        pages += 1

        batch = payload.get("value") or []
        # A delta page mixes changes and removals. `@removed` carries a reason
        # — `deleted` or `changed` — and only the first is a deletion; the
        # second means the item moved out of the scope being synchronised,
        # which is not the same thing and must not tombstone it.
        removals = [m["id"] for m in batch
                    if isinstance(m.get("@removed"), dict)
                    and m["@removed"].get("reason") == "deleted"
                    and m.get("id")]
        present = [m for m in batch if "@removed" not in m and m.get("id")]

        items = [graph_message_to_item(m, address) for m in present]
        added, gone = commit(items, removals)
        added_total += added
        removed_total += gone

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
            "removed": removed_total, "pages": pages,
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

    try:
        who = identity(token, state, refresh=refresh)
        state["identity"] = who
        try:
            report = collect(token, who["address"], state, days)
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
            report = collect(token, who["address"], state, days)
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
