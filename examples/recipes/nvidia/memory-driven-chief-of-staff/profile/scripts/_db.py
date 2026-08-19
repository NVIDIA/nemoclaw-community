# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SQLite access for the ledger.

Two rules, both learned from running this shape under a cron scheduler:

1. One connection per transaction, closed every time. The scheduler can run
   two jobs concurrently, and a connection held open across a model call is a
   lock held for the length of that call.
2. `BEGIN IMMEDIATE`, so a writer takes the write lock up front instead of
   discovering the conflict at COMMIT and losing the work.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


def ledger_path() -> Path:
    """`workspace/` is user-owned, so the store survives profile reinstall."""
    home = os.environ.get("HERMES_HOME")
    if not home:
        raise RuntimeError("HERMES_HOME is not set; refusing to guess the profile home")
    return Path(home) / "workspace" / "ledger" / "state.db"


def ensure_store(schema_sql: Path | None = None) -> Path:
    """Create the directory (0700 — it holds message content) and apply schema."""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if schema_sql is None:
        schema_sql = Path(__file__).with_name("schema.sql")
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.executescript(schema_sql.read_text(encoding="utf-8"))
    return path


@contextlib.contextmanager
def write_txn(path: Path | None = None):
    """Yield a connection inside one immediate transaction.

    Commits on clean exit, rolls back on any exception. Rows and the cursor
    that covers them go through this together, so a crash leaves either both
    or neither — never an advanced watermark over unwritten rows.
    """
    conn = sqlite3.connect(path or ledger_path(), isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
