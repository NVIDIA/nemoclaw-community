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


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _v2_batch_rank(conn: sqlite3.Connection) -> None:
    """Separate the batch position from the global one.

    Before v2 the model's within-batch rank was written straight into
    global_rank, so two batches could each claim positions 1..20 and the caps
    held only inside whichever batch ran last.

    Guarded rather than a bare ALTER, because a store created by the current
    baseline schema already has the column, and a migration that cannot be
    replayed safely is a migration that fails the first time it matters.
    """
    if not _has_column(conn, "obligations", "batch_rank"):
        conn.execute("ALTER TABLE obligations ADD COLUMN batch_rank INTEGER")
        conn.execute("UPDATE obligations SET batch_rank = global_rank"
                     " WHERE batch_rank IS NULL")
    # Clear positions before adding the unique index: pre-v2 data may already
    # contain duplicates, and they are re-derived on the next write anyway.
    conn.execute("UPDATE obligations SET global_rank = NULL WHERE status='open'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_obl_rank_unique"
                 " ON obligations(global_rank)"
                 " WHERE status='open' AND global_rank IS NOT NULL")


# version -> callable applied to reach it. Forward only; there is no down path,
# because a downgrade that drops a column loses data no backup can infer.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _v2_batch_rank,
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
        conn.execute("ROLLBACK")
        conn.close()
        raise
    return conn
