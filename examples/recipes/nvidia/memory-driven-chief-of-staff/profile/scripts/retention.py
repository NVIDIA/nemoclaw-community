# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clear message bodies once they are old enough, and keep everything else.

A store that judges what arrives has no reason to hold the text of it
indefinitely. What stays useful is the record — who wrote, when, what was
decided and why — and that lives in the obligation and its events, not in the
message body. So the body ages out and the history does not.

The line is deliberate. Clearing the body leaves:

- the item row, with sender, subject, timestamp, addressing and state
- the obligation, with the title the judging turn wrote
- every event, with its actor and its before/after

and removes only the sentence somebody typed. A month later the user can still
see that Dana asked for the cutover window on the third, that it was ranked
high because the memory said they had chosen that work, and that they ignored
it on the fifth. They cannot re-read Dana's exact words, which is the point.

`body_cleared_at` marks the difference between a body that was cleared and one
that never existed — a join notice and a message somebody wrote both leave
`body` NULL, and only one of them is a loss.

    python3 retention.py            # clear anything past the window
    python3 retention.py --dry-run  # report what would go, change nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from _db import ensure_store, write_txn

# How long a body stays.
#
# Thirty days is long enough that a person looking back at a decision can still
# read what prompted it, and short enough that a store is not a copy of the
# mailbox. It is the default rather than the rule: `RETENTION_DAYS` moves it.
#
# For the scheduled job, set it in `$HERMES_HOME/.env` — `hermes config
# env-path` prints the file. That is the only place a value survives to the
# next tick: `hermes cron create` and `cron edit` take no environment, so
# exporting the variable in a shell changes the run you are watching and
# nothing after it. Measured: a `.env` line reaches the cron subprocess.
RETENTION_DAYS = 30

MAX_RETENTION_DAYS = 3650


def bounded_days(name: str, default: int) -> int:
    """Read a positive, bounded day count from the environment.

    A zero would clear every body on the next tick, including the one that
    arrived a minute ago, and a negative would make the cutoff sit in the
    future and clear everything ever stored. Both are the kind of mistake that
    is only discovered afterwards, so neither is accepted.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"{name} must be a whole number of days between 1 and "
            f"{MAX_RETENTION_DAYS}; got {raw!r}")
    if value < 1 or value > MAX_RETENTION_DAYS:
        raise SystemExit(
            f"{name} must be between 1 and {MAX_RETENTION_DAYS}; got {value}")
    return value


def cutoff(days: int, now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def survey(conn, before: str) -> dict[str, int]:
    """What the pass would do, without doing it."""
    due = conn.execute(
        "SELECT COUNT(*) FROM items"
        " WHERE event_at < ? AND body IS NOT NULL", (before,)).fetchone()[0]
    kept = conn.execute(
        "SELECT COUNT(*) FROM items WHERE body IS NOT NULL").fetchone()[0] - due
    cleared = conn.execute(
        "SELECT COUNT(*) FROM items WHERE body_cleared_at IS NOT NULL"
    ).fetchone()[0]
    return {"due": due, "still_held": kept, "already_cleared": cleared}


def clear(conn, before: str) -> int:
    """Drop the text, keep the row.

    `subject` stays. On email it is often the only human-readable handle the
    row has, it is what the obligation title was derived from, and it is short
    enough that keeping it does not amount to keeping the message.
    """
    cursor = conn.execute(
        "UPDATE items"
        "   SET body = NULL,"
        "       body_cleared_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        " WHERE event_at < ? AND body IS NOT NULL", (before,))
    return cursor.rowcount


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be cleared and change nothing")
    args = parser.parse_args(argv)

    days = bounded_days("RETENTION_DAYS", RETENTION_DAYS)
    before = cutoff(days)
    ensure_store()

    with write_txn() as conn:
        report = survey(conn, before)
        report["retention_days"] = days
        report["cutoff"] = before
        if args.dry_run:
            report["dry_run"] = True
        else:
            report["cleared"] = clear(conn, before)

    print(json.dumps(report))
    # Retention needs no judgment, so the agent is never woken. Printing the
    # gate last is what the scheduler reads; see `select_intake.py` for the
    # same contract on the collecting side.
    print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
