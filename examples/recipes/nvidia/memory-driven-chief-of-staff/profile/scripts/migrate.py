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

SCHEMA_VERSION = 1

# version -> SQL applied to reach it. Forward only; there is no down path,
# because a downgrade that drops a column loses data no backup can infer.
MIGRATIONS: dict[int, str] = {}


class SchemaFromTheFuture(RuntimeError):
    """The store was written by a newer version of this recipe."""


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations. Returns the versions applied, oldest first."""
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaFromTheFuture(
            f"store is at schema {version}, this code understands {SCHEMA_VERSION}. "
            "Upgrade the recipe rather than downgrading the store.")

    applied: list[int] = []
    for target in range(version + 1, SCHEMA_VERSION + 1):
        sql = MIGRATIONS.get(target)
        if sql:
            conn.executescript(sql)
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
