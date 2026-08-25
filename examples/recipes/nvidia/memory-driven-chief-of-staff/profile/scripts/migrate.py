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

import sqlite3
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 2

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
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _add_body_cleared_at,
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


def open_store(path: Path) -> sqlite3.Connection:
    """Open a store and bring it to the current schema."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
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
