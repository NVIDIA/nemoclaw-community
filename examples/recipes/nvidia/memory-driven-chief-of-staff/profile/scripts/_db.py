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


# Entries Hermes puts in a profile home. `distribution.yaml` is the one Hermes
# itself reads to identify an installed distribution, and this recipe ships it;
# the rest are what a profile carries whether or not a distribution is
# installed. Any single one is enough — a profile part-way through setup is
# still a profile.
PROFILE_MARKERS = ("distribution.yaml", "SOUL.md", ".env",
                   "memories", "sessions", "skills", "cron")

# What this recipe itself creates. A directory holding only these has not been
# identified as a profile yet, but it is one we made, so it is not evidence of
# a wrong target.
OURS = {"workspace"}


def _is_profile_home(root: Path) -> bool:
    """Whether `root` looks like a Hermes profile home.

    The default profile is `~/.hermes` itself and named profiles live at
    `~/.hermes/profiles/<name>`, so the runtime root and a valid profile home
    can be the same directory. The name therefore cannot decide this — an
    earlier version rejected any path ending in `.hermes` and refused the
    default profile outright. A marker can decide it, and applies equally to
    both layouts.
    """
    if any((root / marker).exists() for marker in PROFILE_MARKERS):
        return True
    # A fresh directory is accepted: `hermes profile create` makes the home
    # before anything populates it, and refusing that would mean the store
    # could never be created on a first run.
    return not (set(entry.name for entry in root.iterdir()) - OURS)


def ledger_path() -> Path:
    """`workspace/` is user-owned, so the store survives profile reinstall.

    HERMES_HOME must be set: falling back to a default points every command at
    whichever profile happens to be active, and during development that made a
    reset report deleting a ledger belonging to a different profile entirely.
    """
    home = os.environ.get("HERMES_HOME", "").strip()
    if not home:
        raise RuntimeError("HERMES_HOME is not set; refusing to guess the profile home")
    root = Path(home)
    if root.exists() and not root.is_dir():
        raise RuntimeError(f"HERMES_HOME is not a directory: {root}")
    if root.is_dir() and not _is_profile_home(root):
        raise RuntimeError(
            f"HERMES_HOME does not look like a Hermes profile home: {root}. "
            f"Expected one of {', '.join(PROFILE_MARKERS)} there. The default "
            "profile is the Hermes root itself; named profiles live under "
            "<root>/profiles/<name>.")
    return root / "workspace" / "ledger" / "state.db"


def ensure_store(schema_sql: Path | None = None) -> Path:
    """Open the store, creating or migrating it, and refuse one from the future.

    This is the only initialisation path. Every executable goes through it, so
    the version check cannot be bypassed by reaching for a lower-level helper:
    a store written by a newer version of this recipe is rejected before any
    write rather than being quietly populated with tables it does not expect.
    """
    from migrate import migrate           # imported here to avoid a cycle

    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if schema_sql is None:
        schema_sql = Path(__file__).with_name("schema.sql")

    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        # Creating tables is idempotent, so this is safe on an existing store;
        # it is what brings a brand new one up to the baseline. executescript
        # commits implicitly, so it runs before the transaction rather than
        # inside one.
        conn.executescript(schema_sql.read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        try:
            migrate(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
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
