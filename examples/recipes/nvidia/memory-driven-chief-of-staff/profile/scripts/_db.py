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


def _significant(root: Path) -> set[str]:
    """Directory entries that say something about what this directory is.

    Dotfiles do not. A profile home that someone opened in a file browser picks
    up a `.DS_Store`, and treating that as content made an otherwise empty
    directory look occupied. The markers that *are* dotfiles, `.env` among
    them, are matched before this is reached.
    """
    return {entry.name for entry in root.iterdir()
            if not entry.name.startswith(".")} - OURS


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
    return not _significant(root)


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
    if not root.exists():
        # A path that is merely mistyped is the ordinary way of pointing at the
        # wrong place, and it used to be the one case that got through: the
        # check below only ran on a directory that existed, so a typo skipped
        # it and materialised a whole store under the misspelled name. Refusing
        # is safe because nothing creates a profile home except Hermes.
        raise RuntimeError(
            f"HERMES_HOME does not exist: {root}. Create the profile first "
            "(`hermes profile create <name>`), or point at an existing one — "
            "the default profile is the Hermes root itself and named profiles "
            "live under <root>/profiles/<name>.")
    if not root.is_dir():
        raise RuntimeError(f"HERMES_HOME is not a directory: {root}")
    if not _is_profile_home(root):
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
    from migrate import migrate, refuse_if_from_the_future   # avoids a cycle

    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if schema_sql is None:
        schema_sql = Path(__file__).with_name("schema.sql")

    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        # `sources` is a foreign key, not a CHECK, so that adding a
        # connector is an INSERT rather than a table rebuild. The cost is
        # that SQLite enforces foreign keys per connection: unset, the
        # constraint is inert. Every connection this code opens for writing
        # sets it, here and in `write_txn`.
        conn.execute("PRAGMA foreign_keys = ON")
        # Check the version before the baseline DDL, not after. `CREATE TABLE
        # IF NOT EXISTS` is idempotent against our own schema but not against
        # someone else's: a store from a later version that dropped a table we
        # still ship would have it silently recreated, so "refused before any
        # write" has to mean before the DDL too.
        refuse_if_from_the_future(conn)
        # What the store said before the baseline DDL runs. The DDL carries
        # `INSERT OR IGNORE INTO meta ... ('schema_version', '<current>')`, so
        # on a store whose version row is absent it stamps the current version
        # over a database that has none of the current columns. `migrate` then
        # sees a version equal to its own and does nothing, and the store is
        # left claiming a shape it does not have — which surfaces later as a
        # missing column in a job nobody was watching. Remember the real answer
        # first and put it back afterwards.
        recorded = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone() \
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table'"
                            " AND name='meta'").fetchone() else None

        # Creating tables is idempotent, so this is safe on an existing store;
        # it is what brings a brand new one up to the baseline. executescript
        # commits implicitly, so it runs before the transaction rather than
        # inside one.
        had_tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
            " AND name='items'").fetchone()[0]
        conn.executescript(schema_sql.read_text(encoding="utf-8"))

        # An existing store keeps whatever version it actually had; only a
        # genuinely new one is allowed to start at the baseline. A pre-existing
        # store with no version row is version 0 by definition — unversioned —
        # and must be migrated forward rather than declared current.
        if had_tables:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (recorded[0] if recorded else "0",))
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
        # Roll back only if a transaction actually opened, and never let the
        # rollback's own failure replace the original one. `BEGIN IMMEDIATE`
        # fails on a busy database, at which point there is nothing to roll
        # back — and an unconditional ROLLBACK then raises "cannot rollback -
        # no transaction is active", which is what the caller sees instead of
        # "database is locked". The cleanup would be reported as the fault.
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        raise
    finally:
        conn.close()
