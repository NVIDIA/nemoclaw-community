# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Schema versioning for the ledger.

The store outlives any single version of this example, so it carries a version
and a forward-only migration path. Two properties matter more than the
migrations themselves:

  * running migrations on an up-to-date store does nothing, so every job can
    call it on startup without thinking about it;
  * a store from the future is refused rather than opened, because silently
    operating on a schema you do not understand is how data gets corrupted by
    a downgrade.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 5

# version -> callable applied to reach it. Forward only; there is no down path,
# because a downgrade that drops a column loses data no backup can infer.
#
def _add_body_cleared_at(conn: sqlite3.Connection) -> None:
    """v2: record when the retention pass cleared a body.

    Without it, a cleared message and one that never carried text are the same
    row — both have `body IS NULL` — and the first is something a person wrote
    while the second is a join notice. Retention has to be able to tell them
    apart to report what it did, and a reader has to be able to tell that the
    absence is deliberate.

    Added rather than backfilled: a store upgrading to v2 has had no retention
    pass, so every existing row is correctly NULL here.

    Idempotent, because it has to be. A versionless store is one the baseline
    DDL already built at the current shape — the column is there and only the
    `meta` row is missing — and bringing it up must not fail on a column it
    can see. Checking is cheaper than parsing the error text SQLite returns.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "body_cleared_at" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN body_cleared_at TEXT")


# version -> callable applied to reach it. Forward only; there is no down path,
# because a downgrade that drops a column loses data no backup can infer.
def _add_sender_key(conn: sqlite3.Connection) -> None:
    """v3: somewhere to keep who a sender is, not just what they are called.

    Idempotent: an ALTER that has already happened is detected rather than
    attempted, because a migration that fails on a store it already migrated
    is a migration that only works once.

    Existing rows keep NULL. Backfilling is not possible — the value was never
    stored, and the display name it would have to be derived from is exactly
    the thing that cannot identify anybody.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "sender_key" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN sender_key TEXT")


def _add_removal_tracking(conn: sqlite3.Connection) -> None:
    """v4: somewhere to record that the source removed a message.

    Two columns, one feature. `deleted_at` is the verdict; the message's own
    `internetMessageId` is what the verdict is reached by, and it has to be
    on the row because by the time a removal is reported the message is gone
    and there is nothing left to read it from.

    Added with the Microsoft Graph collector. Idempotent: an ALTER that has
    already happened is detected rather than attempted, because a migration
    that fails on a store it already migrated is a migration that only works
    once.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN deleted_at TEXT")
    if "internet_message_id" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN internet_message_id TEXT")


def _add_identity_model(conn: sqlite3.Connection) -> None:
    """v5: a person is a set of identities, and a source is a row.

    Three changes that only make sense together.

    `sender_handle` records what a source calls somebody — a Slack handle, a
    login — which is neither their identity nor their display name, and is
    the strongest evidence a source offers that the same person appears in
    another one.

    `sources` replaces `CHECK (source IN ('email','slack'))`. That list meant
    a third connector could not write a row until somebody shipped a schema
    change, which is a poor thing to discover while writing the connector.
    SQLite cannot alter a CHECK, so removing it is a table rebuild — the one
    migration shape that can lose rows, which is why the columns are named
    explicitly below rather than copied with `SELECT *`, and why the row
    count is compared before and after.

    `identity_links` holds the user's answers about which identities belong
    to one person. Empty here: this migration adds somewhere to record them
    and does not invent any.

    Idempotent throughout, so an interrupted upgrade can be run again.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "sender_handle" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN sender_handle TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            name      TEXT PRIMARY KEY,
            added_at  TEXT NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )""")
    # Every source any row already claims, so the foreign key added below
    # cannot orphan a message that arrived before this table existed.
    conn.execute("INSERT OR IGNORE INTO sources(name) VALUES ('email'),('slack')")
    conn.execute("INSERT OR IGNORE INTO sources(name)"
                 " SELECT DISTINCT source FROM items WHERE source IS NOT NULL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS identity_links (
            left_source   TEXT NOT NULL REFERENCES sources(name),
            left_key      TEXT NOT NULL,
            right_source  TEXT NOT NULL REFERENCES sources(name),
            right_key     TEXT NOT NULL,
            status        TEXT NOT NULL
                          CHECK (status IN ('confirmed','rejected')),
            decided_at    TEXT NOT NULL
                          DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            decided_via   TEXT NOT NULL DEFAULT 'user',
            PRIMARY KEY (left_source, left_key, right_source, right_key),
            CHECK ((left_source, left_key) < (right_source, right_key))
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_links_left"
                 " ON identity_links(left_source, left_key)"
                 " WHERE status = 'confirmed'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_links_right"
                 " ON identity_links(right_source, right_key)"
                 " WHERE status = 'confirmed'")

    _rebuild_items_without_the_source_check(conn)


ITEM_COLUMNS_V5 = (
    "source_id", "source", "scope", "thread_ref", "event_at", "sender",
    "sender_key", "sender_handle", "subject", "body", "body_cleared_at",
    "deleted_at", "internet_message_id", "permalink", "addressing", "unread",
    "state", "state_at",
)


def _rebuild_items_without_the_source_check(conn: sqlite3.Connection) -> None:
    """Swap `items` for one whose `source` is a foreign key, keeping rows.

    Detected rather than attempted: a store that already has the foreign key
    is left alone, so a re-run costs a `PRAGMA` and nothing else.

    `PRAGMA foreign_keys` is deliberately not touched. The callers that open
    a store for writing set it, and turning it off here would silently do
    nothing anyway — SQLite ignores the pragma inside a transaction. The
    order below does not need it off: nothing has a foreign key to `items`,
    and `sources` is populated before any row is copied, so every row has a
    parent by the time the constraint applies.
    """
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='items'"
    ).fetchone()
    if sql and "REFERENCES sources" in (sql[0] or ""):
        return

    before = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    names = ", ".join(ITEM_COLUMNS_V5)
    conn.execute("""
        CREATE TABLE items_v5 (
            source_id   TEXT PRIMARY KEY,
            source      TEXT NOT NULL REFERENCES sources(name),
            scope       TEXT NOT NULL,
            thread_ref  TEXT,
            event_at    TEXT NOT NULL,
            sender      TEXT,
            sender_key  TEXT,
            sender_handle TEXT,
            subject     TEXT,
            body        TEXT,
            body_cleared_at TEXT,
            deleted_at    TEXT,
            internet_message_id TEXT,
            permalink   TEXT,
            addressing  TEXT
                        CHECK (addressing IN ('direct','mentioned','broadcast')),
            unread      INTEGER CHECK (unread IN (0,1)),
            state       TEXT NOT NULL
                        CHECK (state IN ('pending','judged','skipped'))
                        DEFAULT 'pending',
            state_at    TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )""")
    conn.execute(f"INSERT INTO items_v5({names}) SELECT {names} FROM items")
    after = conn.execute("SELECT count(*) FROM items_v5").fetchone()[0]
    if after != before:
        # The transaction is rolled back by the caller, so the old table is
        # still there. Better to refuse an upgrade than to complete one that
        # dropped messages.
        raise RuntimeError(
            f"rebuilding items would have kept {after} of {before} rows")

    conn.execute("DROP TABLE items")
    conn.execute("ALTER TABLE items_v5 RENAME TO items")
    # Dropping the table dropped its indexes with it.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_pending"
                 " ON items(state, event_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_event_at"
                 " ON items(event_at) WHERE body IS NOT NULL")


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _add_body_cleared_at,
    3: _add_sender_key,
    4: _add_removal_tracking,
    5: _add_identity_model,
}


class SchemaFromTheFuture(RuntimeError):
    """The store was written by a newer version of this recipe."""


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def refuse_if_from_the_future(conn: sqlite3.Connection) -> None:
    """Raise if the store is newer than this code, without touching it.

    Callable before the baseline schema runs, which is the point: `migrate`
    can only check after `meta` exists, so a caller that creates tables first
    has already written to a store it does not understand by the time the
    check fires. A store with no `meta` table has no version to be ahead of,
    so it is left for the baseline to create.
    """
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not has_meta:
        return
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaFromTheFuture(
            f"store is at schema {version}, this code understands {SCHEMA_VERSION}. "
            "Upgrade the recipe rather than downgrading the store.")


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations. Returns the versions applied, oldest first."""
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaFromTheFuture(
            f"store is at schema {version}, this code understands {SCHEMA_VERSION}. "
            "Upgrade the recipe rather than downgrading the store.")

    applied: list[int] = []
    for target in range(version + 1, SCHEMA_VERSION + 1):
        step = MIGRATIONS.get(target)
        if step:
            step(conn)
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(target),))
        applied.append(target)
    return applied


def main(argv: list[str] | None = None) -> int:
    """Bring the store at `$HERMES_HOME` to the current schema.

    `docs/data-lifecycle.md` told people to run this file and it had no entry
    point, so `python3 migrate.py` did nothing at all and left a v1 store at
    v1 — an instruction that reported success by saying nothing. Migration
    does happen on its own through `ensure_store()`, which every executable
    goes through; this exists so the documented command is real, and so
    somebody can do it deliberately before a job does it for them.
    """
    import argparse

    from _db import ensure_store, ledger_path

    parser = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report the version and change nothing")
    args = parser.parse_args(argv)

    if args.check:
        path = ledger_path()
        if not path.exists():
            print(json.dumps({"store": str(path), "exists": False}))
            return 0
        with contextlib.closing(sqlite3.connect(path)) as conn:
            print(json.dumps({"store": str(path), "exists": True,
                              "schema_version": current_version(conn),
                              "code_understands": SCHEMA_VERSION}))
        return 0

    path = ensure_store()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        version = current_version(conn)
    print(json.dumps({"store": str(path), "schema_version": version}))
    return 0


def open_store(path: Path) -> sqlite3.Connection:
    """Open a store and bring it to the current schema."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    # Per connection, and inert without it — see `_db.ensure_store`. Set
    # before BEGIN: SQLite ignores this pragma inside a transaction.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        migrate(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        conn.close()
        raise
    return conn


if __name__ == "__main__":
    raise SystemExit(main())
