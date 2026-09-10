# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persist user skill overrides with explicit distribution provenance.

Only ``--record-distribution /path/to/reviewed/recipe/profile`` registers
shipped bases. The installer calls it with the source it just installed.
Apply, check, fork, remove and reset never promote unknown live bytes to
shipped content. After a bare Hermes update, record that update's reviewed
source before applying overrides; a stale override remains blocked until
its author rebases it deliberately.

Each skill has a lock and a durable apply/remove journal. A global lock
coordinates distribution registration, recovery snapshots, restore and reset.
Hermes does not take these locks: stop the profile's jobs and avoid running
Hermes updates concurrently with these commands. The locks coordinate only
this recipe's own commands.

``--restore BUNDLE`` restores this feature's files and SQLite history from
export_store.py's versioned recovery bundle. It never writes live skills;
the next explicit or scheduled apply validates them against the restored
base relationship. An unknown installed version is refused.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def profile_root() -> Path:
    """The installed profile home — everything else in this module is
    relative to it. Reuses `_db.ledger_path`'s own `HERMES_HOME` validation
    rather than repeating it, the same way `select_memory.memory_root` does.
    """
    from _db import ledger_path
    return ledger_path().parent.parent.parent


def _state_dir(root: Path) -> Path:
    """Every hop from `root` down checked, not just the last one — a
    symlinked `workspace` or `workspace/skill-overrides` is exactly as
    unsafe as a symlinked `overrides` or `bases` underneath it, and a
    `_safe_child` call given an already-composed multi-level path as its
    `parent` only ever re-checks that one path, never the hops baked into
    how it was built.
    """
    return _safe_child(root, "workspace", "skill-overrides")


def _overrides_dir(root: Path) -> Path:
    return _safe_child(_state_dir(root), "overrides")


def _bases_dir(root: Path) -> Path:
    return _safe_child(_state_dir(root), "bases")


def _db_path(root: Path) -> Path:
    return _safe_child(_state_dir(root), "state.db")


def _skills_dir(root: Path) -> Path:
    # One hop below `root`, and every caller already passes this as the
    # `parent` argument to its own `_safe_child` call, which checks it —
    # unlike `_state_dir` and what sits under it, nothing here composes
    # this path as an intermediate hop the way `_overrides_dir` composes
    # `_state_dir`, so no separate check is needed at construction time.
    return root / "skills"


def _locks_dir(root: Path) -> Path:
    return _safe_child(_state_dir(root), "locks")


def _global_lock_path(root: Path) -> Path:
    # Deliberately a sibling of `skill-overrides/`, not inside it:
    # `reset.py` deletes that whole tree, and a lock every operation
    # depends on to know reset is not running has to survive exactly the
    # deletion it exists to guard. `_safe_child` from `root`, not plain
    # concatenation, so a symlinked `workspace` cannot make this open and
    # flock a file outside the profile before anything else has a chance
    # to reject it.
    return _safe_child(root, "workspace", ".skill-overrides-global.lock")


@contextlib.contextmanager
def _global_lock(root: Path, *, exclusive: bool):
    """A shared/exclusive barrier around every skill's own lock — not a
    substitute for it. Every ordinary operation holds this in shared mode
    for as long as it holds a skill's own lock, so any number of them run
    fully concurrently against each other (shared locks never conflict
    with other shared locks) — this changes nothing about their mutual
    independence. `reset.py` is the only caller that ever asks for
    `exclusive=True`, and only around the moment it deletes
    `workspace/skill-overrides/`: acquiring the exclusive lock blocks
    until every currently-shared holder has finished and released, and
    once held, blocks any new one from starting — the actual barrier a
    one-time best-effort check of who currently holds what can only ever
    approximate.
    """
    lock_path = _global_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _skill_lock(root: Path, skill_name: str):
    """Real mutual exclusion for one skill, held across an entire
    claim-write-complete sequence — not a database row two processes can
    each believe they own in turn.

    A SQLite transaction cannot be this lock: holding one open across a
    filesystem write blocks every other skill's writer too, since SQLite
    has one write lock for the whole database file, not one per row —
    which is exactly the trade a hash-comparison-based "claim" was trying
    to make instead, and exactly why that could still let two processes
    each finish believing they won. A plain `flock` on a small per-skill
    file has none of that coupling: two different skills' locks are two
    different files, so contention on one never touches the other, and
    while one process holds a skill's lock, nothing else — not a second
    `--apply` tick, not a concurrent `--fork` or `--remove` — can even
    begin claiming an operation for that same skill until it is released.

    Nested inside the global shared lock, not instead of it: this alone
    stops two operations from racing each other on the *same* skill, but
    says nothing about a reset running concurrently with a *different*
    skill's operation — closing that needs every ordinary operation and
    a reset to agree on when it is safe to proceed at all, which only the
    global lock's exclusive mode does. `reset.py` holds that exclusive
    lock across its own entire restore-then-delete epoch and uses
    `_skill_lock_only` directly (see that function) rather than this one,
    since re-acquiring the global lock in shared mode while already
    holding it exclusively, from the same process, would deadlock.
    """
    with _global_lock(root, exclusive=False):
        with _skill_lock_only(root, skill_name):
            yield


@contextlib.contextmanager
def _skill_lock_only(root: Path, skill_name: str):
    """The per-skill flock alone, with no global-lock involvement —
    correct to use directly only when the caller already holds the
    global lock some other way (today, only `reset.py`, which holds it
    exclusively for its whole restore-then-delete epoch). Every ordinary
    caller should use `_skill_lock` instead, not this.
    """
    lock_dir = _locks_dir(root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(lock_dir, 0o700)
    lock_path = _safe_child(lock_dir, f"{skill_name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Skill name validation and path containment
# ---------------------------------------------------------------------------

# What a real shipped skill directory name can be. Rejects path separators
# and traversal sequences outright, before any path is built from one.
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InvalidSkillName(ValueError):
    pass


def _validate_skill_name(name: str) -> None:
    if not SKILL_NAME.match(name):
        raise InvalidSkillName(
            f"{name!r} is not a valid skill name (expected lowercase "
            "letters, digits and single hyphens, no path separators)")


class UnsafePath(RuntimeError):
    """A resolved path escaped its intended parent, or crossed a symlink."""


def _safe_child(parent: Path, *parts: str) -> Path:
    """`parent/parts...`, refusing symlinks and containment escapes.

    Checked immediately before every use, not once at the start of a run —
    a symlink introduced between an earlier check and this one is exactly
    the race a single up-front check misses. This closes the race for
    this feature's own cooperating writers (cron, `--fork`/`--apply`/
    `--remove`, all going through this same function); it does not and
    cannot fully close a race against an arbitrary uncooperative process
    with equivalent filesystem access, which no user-space file-based
    design can — a real close needs directory-file-descriptor-relative
    (`openat`-style) operations this module does not use.

    `parent` itself is checked too, not just the parts appended to it —
    a symlinked `skills/`, `overrides/`, or `bases/` directory is exactly
    as unsafe as a symlinked entry inside one of them.
    """
    # `_is_symlink_strict`, not `Path.is_symlink()`: the plain method
    # folds any `OSError` into `False`, and a false negative here is not
    # like one anywhere else this module fixed it — `parent_resolved`
    # below becomes the actual containment anchor every subsequent
    # check trusts, so a symlinked `parent` slipping past this on a
    # transient error would make an external target the accepted root
    # for every live-file, lock, override, and database path built from
    # it afterward, not merely miss one skill's worth of state.
    if _is_symlink_strict(parent):
        raise UnsafePath(f"{parent} is a symlink; refusing to use it")
    parent_resolved = parent.resolve()
    candidate = parent
    for part in parts:
        candidate = candidate / part
        if _is_symlink_strict(candidate):
            raise UnsafePath(f"{candidate} is a symlink; refusing to use it")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(parent_resolved)
    except ValueError:
        raise UnsafePath(
            f"{candidate} resolves to {resolved}, outside {parent_resolved}")
    return candidate


# ---------------------------------------------------------------------------
# Frontmatter — a small local parser, matching this recipe's established
# style (memory_check.py has its own copy too; each script stays self-
# contained rather than importing a shared module for a few lines of regex).
# ---------------------------------------------------------------------------

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Database
#
# `override_operations` has exactly two states on purpose. The row for a
# write is inserted and committed *before* the write happens — that commit
# is the only thing that has to survive a crash — and is marked `complete`
# in a second, separate commit once every side effect of that write (the
# manifest row, an override file's removal) is done. There is nothing a
# crash can leave in between those two commits that isn't either "the row
# never landed" (nothing to recover) or "the row landed, file content says
# whether the write itself happened yet" — a four-state journal here would
# describe transitions this design never lets a crash actually produce.
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS base_blobs (
    content_hash TEXT PRIMARY KEY,
    first_observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS base_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name      TEXT NOT NULL,
    content_hash    TEXT NOT NULL REFERENCES base_blobs(content_hash),
    observed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS base_observations_skill
    ON base_observations(skill_name, observation_id);

CREATE TABLE IF NOT EXISTS approved_bases (
    skill_name TEXT NOT NULL,
    content_hash TEXT NOT NULL REFERENCES base_blobs(content_hash),
    PRIMARY KEY (skill_name, content_hash)
);
CREATE TABLE IF NOT EXISTS distribution_bases (
    skill_name TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL REFERENCES base_blobs(content_hash)
);

CREATE TABLE IF NOT EXISTS applied_overrides (
    skill_name   TEXT PRIMARY KEY,
    applied_hash TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS override_operations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name    TEXT NOT NULL,
    op_type       TEXT NOT NULL CHECK (op_type IN ('apply','remove')),
    status        TEXT NOT NULL CHECK (status IN ('pending','complete'))
                  DEFAULT 'pending',
    expected_before_hash TEXT NOT NULL,
    expected_after_hash  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS override_operations_inflight
    ON override_operations(skill_name) WHERE status != 'complete';
"""


def _connect(root: Path) -> sqlite3.Connection:
    state_dir = _state_dir(root)
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    conn = sqlite3.connect(_db_path(root), isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    os.chmod(_db_path(root), 0o600)
    return conn


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _pending_operation_row(conn: sqlite3.Connection,
                           skill_name: str) -> tuple[str, str, str] | None:
    """`(op_type, expected_before_hash, expected_after_hash)` for this
    skill's still-`pending` operation row, or `None` if it has none."""
    return conn.execute(
        "SELECT op_type, expected_before_hash, expected_after_hash"
        " FROM override_operations WHERE skill_name = ? AND status != 'complete'",
        (skill_name,)).fetchone()


def _pending_operation_diverged(conn: sqlite3.Connection, skill_name: str,
                                live_hash: str) -> bool:
    """Whether this skill has a still-pending operation whose live
    content matches neither its recorded starting point nor its intended
    result — something outside this module's cooperating writers changed
    it since. `False` covers both "no pending operation at all" and "the
    pending one is a legitimate retry or landed-but-unreconciled write".

    Every caller of this shares the same stake: recording genuinely
    diverged content as a trusted new shipped base (`_observe_if_new`),
    or silently discarding the one row that explains it (reset's bulk
    deletion, once nothing is left to gate on), would both break
    `reconcile()`'s own "left untouched" / "blocked from automated
    apply/remove" promise for this skill.
    """
    pending = _pending_operation_row(conn, skill_name)
    if pending is None:
        return False
    _, pending_before, pending_after = pending
    return live_hash not in (pending_before, pending_after)


def _pending_operation_verdict(conn: sqlite3.Connection, skill_name: str,
                               op_type: str, live_hash: str) -> Report | None:
    """Whether a still-pending operation on this skill must block `apply`
    or `remove` before anything — even just observing live content as a
    new base — touches it further. `None` means it is safe to proceed
    into the ordinary claim/observe flow; a `Report` means stop now,
    before observing anything.

    Two different reasons to block, checked in order:

    Genuine divergence (see `_pending_operation_diverged`) is never safe
    to proceed past, regardless of which operation is asking.

    A pending operation of a *different* kind whose write has not yet
    landed (live still matches its own recorded starting point) is
    `_claim_operation`'s own signal to reuse that row rather than insert
    a second one — which would silently repurpose it: a still-pending
    `remove` reused as an `apply`, or vice versa, cancels whichever
    intent was there first without so much as a report saying so. Only
    a matching op_type, or a pending op that has already landed (live
    matches its recorded *after* state, which is what `_is_own_write`
    recognizes as safe to observe as "ours" further down), is left to
    fall through normally.
    """
    if _pending_operation_diverged(conn, skill_name, live_hash):
        return Report(
            "blocked", skill_name,
            "a previous operation on this skill is still unresolved, and "
            "the live content no longer matches what it expected; run "
            "--check, investigate, and clear it by hand before this "
            "skill is touched again automatically")
    pending = _pending_operation_row(conn, skill_name)
    if pending is not None:
        pending_op_type, pending_before, _pending_after = pending
        if pending_op_type != op_type and live_hash == pending_before:
            return Report(
                "blocked", skill_name,
                f"a previous {pending_op_type} operation on this skill is "
                "still pending and has not yet been retried or resolved; "
                "resolving it first (re-run the matching command, or "
                "investigate with --check and clear it by hand) avoids "
                "silently replacing it with a different kind of operation")
    return None


def _pending_operation_check_report(conn: sqlite3.Connection,
                                    skill_name: str,
                                    live_hash: str) -> Report | None:
    """Describe unresolved journal state without reconciling or hiding it.

    The mutating commands reconcile pending rows before they continue. A
    read-only check cannot do that, but it must still report the row: otherwise
    it can claim an override is ready while the corresponding apply would stop
    on a pending remove, or while an interrupted write still needs recovery.
    """
    pending = _pending_operation_row(conn, skill_name)
    if pending is None:
        return None
    op_type, before_hash, after_hash = pending
    if live_hash not in (before_hash, after_hash):
        return Report(
            "blocked", skill_name,
            f"a previous {op_type} operation is still pending, and live "
            "content matches neither its expected starting point nor its "
            "intended result; resolve it by hand before this skill is "
            "touched again automatically")
    state = ("its intended write has landed but its bookkeeping is incomplete"
             if live_hash == after_hash else
             "its intended write has not landed")
    retry = "--apply" if op_type == "apply" else f"--remove {skill_name}"
    return Report(
        "blocked", skill_name,
        f"a previous {op_type} operation is still pending and {state}; "
        f"--check cannot reconcile it because --check writes nothing — run "
        f"{retry} to finish the operation")


def _claim_operation(conn: sqlite3.Connection, skill_name: str, op_type: str,
                     before_hash: str, after_hash: str) -> tuple[int | None, str | None]:
    """Durably record the write this skill is about to make, before making
    it — reusing a row `reconcile()` already put back to `pending` for
    this exact starting point rather than colliding with it.

    A non-`complete` row already existing for this skill means one of two
    things: `reconcile()` looked at it and found live content matching
    the write's own recorded starting point (safe — this is exactly what
    a retried, never-finished write looks like, so its row is reused
    rather than inserting a second one the partial unique index would
    reject anyway), or `reconcile()` found live content matching neither
    the expected before nor after state (unsafe — something outside this
    module's cooperating writers changed it, and this skill is refused
    until a human resolves it).

    Returns `(op_id, None)` when it is safe to proceed, or
    `(None, reason)` when it is not.
    """
    existing = conn.execute(
        "SELECT id, expected_before_hash FROM override_operations"
        " WHERE skill_name = ? AND status != 'complete'", (skill_name,)
    ).fetchone()
    if existing is None:
        op_id = conn.execute(
            "INSERT INTO override_operations"
            "(skill_name, op_type, expected_before_hash, expected_after_hash)"
            " VALUES (?, ?, ?, ?)",
            (skill_name, op_type, before_hash, after_hash)).lastrowid
        return op_id, None
    existing_id, existing_before = existing
    if existing_before != before_hash:
        return None, (
            "a previous operation on this skill is still unresolved, and "
            "the live content no longer matches what it expected; run "
            "--check, investigate, and clear it by hand before this skill "
            "is touched again automatically")
    conn.execute(
        "UPDATE override_operations SET op_type = ?, expected_after_hash = ?"
        " WHERE id = ?", (op_type, after_hash, existing_id))
    return existing_id, None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Report:
    kind: str
    skill: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.skill} — {self.detail}"


# Kinds a caller (install.sh, a human) should treat as needing attention —
# used only to decide the process exit status, never to hide the finding
# itself, which is always in the printed JSON regardless. `skipped-stale`
# is included on purpose, not excluded the way an earlier design left it:
# a shipped update landing after a fork is exactly the moment a newer
# safety or correctness fix in that update could otherwise be silently
# overwritten by content nobody has reviewed against it — the quieter of
# the two dangers a curated layer surviving an update has to guard
# against, the louder one being an update that discards a user's tuning
# outright. Leaving it out of PROBLEM_KINDS traded a real risk for
# avoiding routine alert noise; it belongs here instead, and a `--fork`
# resolves it in one command once someone has actually looked.
# `skipped-exists`/`skipped-no-override`/`reconciled-retry`/
# `reconciled-complete`/`reconciled-abandoned` are the ordinary, expected
# outcome of an idempotent command finding nothing left to do, not a
# failure either.
PROBLEM_KINDS = frozenset({
    "skipped-invalid", "skipped-missing-base", "skipped-no-base",
    "skipped-unknown-skill", "skipped-stale", "orphaned-override", "error",
    "blocked", "reconciled-diverged", "reconciled-error",
})


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` with no window where a reader sees a partial
    file, no predictable temporary name a symlink placed in advance could
    be swapped in for, and no dependence on the OS write-back cache for a
    crash landing between this call and the next process that reads the
    result — `fsync` on the temp file makes its content durable before the
    rename, and `fsync` on the directory makes the rename itself durable;
    without the second one, a power loss can leave a filesystem that
    still shows the old name even though the new file was fully written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _fsync_dir(path: Path) -> None:
    """Makes a directory entry's removal (or creation) durable — an
    `unlink` on its own only guarantees the *file's* content is gone, not
    that the directory entry pointing to it has actually reached disk;
    without this, a power loss right after a successful `--remove` can
    still show the override file on the next boot even though this
    process already reported it deleted.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _regular_file_exists(path: Path) -> bool:
    """True if `path` is a regular file, False only if it does not exist
    at all — unlike `Path.is_file()`, which returns False for *any*
    `OSError` it hits (permission denied, a parent directory that
    briefly became unsearchable, ...), silently folding "does not exist"
    and "exists but could not be checked right now" into the same
    answer. That distinction has to survive here: several callers use
    this exact check to decide whether an override is customized state a
    destructive or completeness-promising command must account for, and
    treating "temporarily unreadable" as "not there" would let one of
    those commands report success while quietly skipping real state.
    `FileNotFoundError` is the only outcome this treats as "not there";
    every other `OSError` propagates, and so does the object existing
    but being something other than a regular file — a directory sitting
    where `SKILL.md` should be is not "no override" either, and silently
    treating it as absent would omit it the same way a permission error
    would.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath(f"{path} exists but is not a regular file")
    return True


def _is_dir_strict(path: Path) -> bool:
    """Like `Path.is_dir()`, but only `FileNotFoundError` means "not
    there" — see `_regular_file_exists` for why that distinction has to
    survive instead of being folded into `Path.is_dir()`'s blanket
    catch-all. Existing but not a directory is a real, different answer
    (`False`, same as `Path.is_dir()` gives it) rather than an error,
    since plenty of callers use this exactly to tell "not created yet"
    from "something else is there" and treat the latter as a genuine
    refusal elsewhere (e.g. `_safe_child`'s own symlink checks).
    """
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except FileNotFoundError:
        return False


def _is_symlink_strict(path: Path) -> bool:
    """Like `Path.is_symlink()`, but only `FileNotFoundError` means "not
    there" — see `_regular_file_exists` for why. Uses `os.lstat`
    directly, the same call `Path.is_symlink()` wraps, so a symlink
    itself is inspected rather than whatever it points at.
    """
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Observation — the rule that works for cron and install.sh alike
# ---------------------------------------------------------------------------


def _is_own_write(conn: sqlite3.Connection, skill_name: str, live_hash: str) -> bool:
    """Whether `live_hash` is this feature's own applied override for
    `skill_name`, not a genuine shipped version — checked against a
    completed `applied_overrides` row first, and, failing that, a still-
    `pending` apply operation whose expected result matches. The second
    check is what makes this correct in exactly the window a crash can
    leave: the file write can land before the completion transaction
    that would otherwise be the only thing recording it as "ours" —
    without this, that live content reads as an unclaimed fresh shipped
    version to anything that observes it in that window, including a
    concurrent reset's own restoration pass.
    """
    applied = conn.execute(
        "SELECT applied_hash FROM applied_overrides WHERE skill_name = ?",
        (skill_name,)).fetchone()
    if applied is not None and applied[0] == live_hash:
        return True
    return conn.execute(
        "SELECT 1 FROM override_operations"
        " WHERE skill_name = ? AND op_type = 'apply'"
        " AND status != 'complete' AND expected_after_hash = ?",
        (skill_name, live_hash)).fetchone() is not None


class UnverifiedBase(RuntimeError):
    """Live content has no accepted distribution provenance."""


def record_distribution(root: Path, source: Path) -> list[Report]:
    """Register a complete distribution from the source chosen by its operator.

    This is an explicit trust boundary, not signature verification. The caller
    must use the same reviewed recipe checkout used for installation. Never
    infer a distribution from the installed profile or from its workspace.
    No live skill is changed, including a name removed by this distribution.
    """
    source = source.absolute()
    installed = root.resolve()
    if source.resolve() == installed or installed in source.resolve().parents:
        raise UnverifiedBase("use the reviewed recipe source, not the installed profile")
    skills = _safe_child(source, "skills")
    payload = {}
    for entry in sorted(skills.iterdir()):
        if entry.name.startswith("."):
            continue
        _validate_skill_name(entry.name)
        path = _safe_child(skills, entry.name, "SKILL.md")
        if not _regular_file_exists(path):
            raise UnverifiedBase(f"distribution skill {entry.name} has no SKILL.md")
        content = path.read_text(encoding="utf-8")
        fm = _frontmatter(content)
        if fm.get("name") != entry.name or not fm.get("description"):
            raise UnverifiedBase(f"invalid distribution frontmatter for {entry.name}")
        payload[entry.name] = content

    with _global_lock(root, exclusive=True):
        conn = _connect(root)
        try:
            if conn.execute("SELECT 1 FROM override_operations WHERE status = 'pending'").fetchone():
                raise UnverifiedBase("resolve pending operations before recording a distribution")
            # Retain bytes before committing their references. A crash leaves
            # at most an unreferenced blob, never an approved missing file.
            for content in payload.values():
                _atomic_write(_safe_child(_bases_dir(root), _sha256(content), "SKILL.md"), content)
            conn.execute("BEGIN IMMEDIATE")
            previous = dict(conn.execute("SELECT skill_name, content_hash FROM distribution_bases"))
            conn.execute("DELETE FROM distribution_bases")
            for name, content in payload.items():
                digest = _sha256(content)
                conn.execute("INSERT OR IGNORE INTO base_blobs(content_hash) VALUES (?)", (digest,))
                conn.execute("INSERT OR IGNORE INTO approved_bases VALUES (?, ?)", (name, digest))
                conn.execute("INSERT INTO distribution_bases VALUES (?, ?)", (name, digest))
                if previous.get(name) != digest:
                    conn.execute("INSERT INTO base_observations(skill_name, content_hash) VALUES (?, ?)",
                                 (name, digest))
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise
        finally:
            conn.close()
    return [Report("distribution-recorded", name, f"accepted source hash {_sha256(content)}")
            for name, content in payload.items()]


def _latest_base(conn: sqlite3.Connection, skill_name: str) -> str | None:
    # Old automatically observed history is retained for export, never
    # grandfathered into trusted content during the upgrade.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='distribution_bases'").fetchone():
        return None
    row = conn.execute("SELECT content_hash FROM distribution_bases WHERE skill_name = ?",
                       (skill_name,)).fetchone()
    return row[0] if row else None


def _observe_if_new(conn: sqlite3.Connection, root: Path, skill_name: str,
                    live_text: str) -> None:
    """Validate live bytes; never create an observation from them."""
    latest = _latest_base(conn, skill_name)
    if latest is None:
        raise UnverifiedBase("skill is absent from the accepted distribution; record the reviewed source")
    live_hash = _sha256(live_text)
    if live_hash != latest and not _is_own_write(conn, skill_name, live_hash):
        raise UnverifiedBase("unknown live content; record the reviewed update source or restore the installed file from it")


def _observed_for_skill(conn: sqlite3.Connection, skill_name: str,
                        content_hash: str) -> bool:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approved_bases'").fetchone():
        return False
    return conn.execute("SELECT 1 FROM approved_bases WHERE skill_name = ? AND content_hash = ?",
                        (skill_name, content_hash)).fetchone() is not None


def _base_text(root: Path, content_hash: str) -> str | None:
    """The retained content for `content_hash`, or None if it is missing or
    does not actually hash to the value claimed — format validity of a
    hash string is not proof its content still exists or matches. Callers
    that need to know the hash was observed for a *specific* skill check
    `_observed_for_skill` first; this only proves the blob itself is real.
    """
    path = _safe_child(_bases_dir(root), content_hash, "SKILL.md")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if _sha256(text) != content_hash:
        return None
    return text


# ---------------------------------------------------------------------------
# Override validation
# ---------------------------------------------------------------------------


def _validate_override_text(conn: sqlite3.Connection, root: Path,
                            skill_name: str, text: str) -> str | None:
    fm = _frontmatter(text)
    if not fm:
        return "override has no frontmatter block"
    if fm.get("name") != skill_name:
        return f"frontmatter `name` must be {skill_name!r} to match its directory"
    if not fm.get("description"):
        return "frontmatter has no `description`"
    based_on = fm.get("based_on_sha256")
    if not based_on:
        return "frontmatter has no `based_on_sha256`"
    if not SHA256_HEX.match(based_on):
        return "frontmatter `based_on_sha256` is not a 64-character hex sha256"
    if not _observed_for_skill(conn, skill_name, based_on):
        return (f"based_on_sha256 {based_on[:12]} was never observed for "
                "this skill (it may belong to a different skill, or this "
                "skill's retained history was reset)")
    if _base_text(root, based_on) is None:
        return (f"based_on_sha256 {based_on[:12]} has no matching retained "
                "blob content on disk")
    return None


# ---------------------------------------------------------------------------
# Skill enumeration — pure filesystem listing, no database involved
# ---------------------------------------------------------------------------


def _list_skill_names(root: Path) -> list[str]:
    skills_dir = _skills_dir(root)
    if not skills_dir.is_dir() or skills_dir.is_symlink():
        return []
    try:
        return sorted(
            p.name for p in skills_dir.iterdir()
            if p.is_dir() and not p.is_symlink() and SKILL_NAME.match(p.name))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Check — per skill, strictly read-only: no observation, no transaction,
# no write anywhere, including its own bookkeeping.
# ---------------------------------------------------------------------------


def _list_overridden_skill_names(root: Path) -> list[str]:
    """Every skill with an override on disk, whether or not it is still
    shipped — the union of this and `_list_skill_names` is what `--check`
    and `--apply` actually walk, so a skill upstream removed but still
    holding an override is reported rather than silently disappearing.

    Graceful, not raising, on the same reasoning as `_list_skill_names`:
    this is a top-level listing that decides what gets processed at all,
    not one skill's own processing — an unsafe tree here degrades to "no
    names found" rather than aborting every skill's run.
    """
    workspace_dir = root / "workspace"
    if workspace_dir.is_symlink():
        return []
    state_dir = workspace_dir / "skill-overrides"
    if state_dir.is_symlink():
        return []
    overrides_dir = state_dir / "overrides"
    if not overrides_dir.is_dir() or overrides_dir.is_symlink():
        return []
    try:
        return sorted(
            p.name for p in overrides_dir.iterdir()
            if p.is_dir() and not p.is_symlink() and SKILL_NAME.match(p.name))
    except OSError:
        # A listing failure here decides what gets processed at all, not
        # one skill's own outcome — degrade to "found nothing" the same
        # way an absent or symlinked directory already does, rather than
        # aborting every skill's run over a directory-level read error.
        return []


def _check_one_skill(root: Path, skill_name: str) -> Report | None:
    """Report accepted-base and live-content checks without writing state."""
    override_file = _safe_child(_overrides_dir(root), skill_name, "SKILL.md")
    has_override_file = _regular_file_exists(override_file)
    live_file = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
    live_text = (live_file.read_text(encoding="utf-8")
                 if live_file.is_file() else None)

    db_path = _db_path(root)
    if not db_path.is_file():
        if not has_override_file:
            return None
        if live_text is None:
            return Report(
                "orphaned-override", skill_name,
                "the installed skill file is missing; inspect the accepted "
                "distribution before restoring or retiring its override")
        return Report("skipped-invalid", skill_name,
                      "no retained history exists for this skill yet "
                      "(nothing has been accepted); run --record-distribution "
                      "with the reviewed recipe source first")

    # Read-only at the SQLite level too, not just by discipline: opened
    # this way, a write anywhere in this function would raise rather than
    # silently succeed. `as_uri()` percent-encodes the path itself, so a
    # profile path that happens to contain `?` or `#` cannot be misread
    # as part of the query string appended after it — but it also refuses
    # a relative path outright, which `HERMES_HOME` is not required to
    # avoid, so `resolve()` comes first.
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        live_hash = _sha256(live_text) if live_text is not None else ""
        pending_report = _pending_operation_check_report(
            conn, skill_name, live_hash)
        if pending_report is not None:
            return pending_report
        if not has_override_file:
            return None
        if live_text is None:
            return Report(
                "orphaned-override", skill_name,
                "the installed skill file is missing; inspect the accepted "
                "distribution before restoring or retiring its override")

        override_text = override_file.read_text(encoding="utf-8")

        reason = _validate_override_text(conn, root, skill_name, override_text)
        if reason:
            return Report("skipped-invalid", skill_name, reason)
        fm = _frontmatter(override_text)
        based_on = fm["based_on_sha256"]

        _observe_if_new(conn, root, skill_name, live_text)
        baseline = _latest_base(conn, skill_name)

        if baseline is not None and based_on != baseline:
            return Report(
                "skipped-stale", skill_name,
                f"override was forked from a different shipped version "
                f"(recorded {based_on[:12]}, latest known is "
                f"{baseline[:12]}); --apply will refuse it until you "
                "export the edit, then --remove and --fork to rebase it")
        if live_hash == _sha256(override_text):
            detail = "override is already live and matches its accepted base"
        else:
            detail = "override is ready to apply against its accepted base"
        return Report("applied", skill_name, detail)
    except UnverifiedBase as exc:
        return Report("blocked", skill_name, str(exc))
    finally:
        conn.close()


def check_overrides(root: Path) -> list[Report]:
    """Read-only: report what applying would do, write nothing — not even
    a new base observation, not even this feature's own journal, and not
    even its own bookkeeping database file when nothing has ever used it."""
    reports: list[Report] = []
    try:
        pending_names = _list_pending_operation_skill_names(root)
    except Exception as exc:
        pending_names = []
        reports.append(Report(
            "error", "pending operations", f"{type(exc).__name__}: {exc}"))
    names = sorted(set(_list_skill_names(root))
                   | set(_list_overridden_skill_names(root))
                   | set(pending_names))
    for name in names:
        try:
            report = _check_one_skill(root, name)
        except Exception as exc:
            report = Report("error", name, f"{type(exc).__name__}: {exc}")
        if report is not None:
            reports.append(report)
    return reports


def _overridden_skill_names_strict(root: Path) -> list[str]:
    """Like `_list_overridden_skill_names`, but raises instead of
    degrading to "found nothing" on a listing failure.

    `--check`/`--apply` use the lenient version deliberately: a top-level
    listing failure there should not abort every other skill's own
    processing. Export's contract is different and stricter — "nothing is
    omitted" — so a listing failure here must abort the export outright.
    Silently returning `[]` would let export finish and report success
    while an unshipped skill's orphaned override was never even
    considered, let alone captured.
    """
    # `_is_symlink_strict`/`_is_dir_strict`, not `Path.is_symlink()`/
    # `Path.is_dir()` — the plain `Path` methods swallow any `OSError`
    # into `False`, which would let an unreadable `overrides/` (or an
    # unreadable child of it) silently look like "not a symlink" and
    # "not a directory" instead of raising, reproducing the exact
    # false-negative this function exists to refuse.
    workspace_dir = root / "workspace"
    if _is_symlink_strict(workspace_dir):
        raise UnsafePath(f"{workspace_dir} is a symlink; refusing to use it")
    state_dir = workspace_dir / "skill-overrides"
    if _is_symlink_strict(state_dir):
        raise UnsafePath(f"{state_dir} is a symlink; refusing to use it")
    overrides_dir = state_dir / "overrides"
    if _is_symlink_strict(overrides_dir):
        raise UnsafePath(f"{overrides_dir} is a symlink; refusing to use it")
    if not _is_dir_strict(overrides_dir):
        return []
    names = []
    for p in overrides_dir.iterdir():
        if not SKILL_NAME.match(p.name):
            continue
        if _is_symlink_strict(p):
            # `_list_overridden_skill_names`'s lenient version silently
            # filters this out — fine for `--check`/`--apply`, where one
            # skill's odd state should not stop every other skill from
            # being processed. Export's "nothing is omitted" contract
            # means silently dropping a skill name here is exactly the
            # failure this function exists to refuse instead of
            # reproducing.
            raise UnsafePath(f"{p} is a symlink; refusing to use it")
        if _is_dir_strict(p):
            names.append(p.name)
    return sorted(names)


def snapshot_for_export(root: Path, *, locked: bool = False) -> list[tuple[Report, str | None]]:
    """Like `check_overrides`, but pairs each report with that override's
    exact text at the same instant, captured under that skill's own lock
    — used by `export_store.py`, which otherwise reads a status and
    copies a file as two separate, unlocked operations a concurrent
    `--apply`/`--fork`/`--remove` could land in between, producing a
    report that describes one version while the file it sits next to
    holds another.

    Deliberately does not catch its own failures into an "error" Report
    the way `_check_one_skill`'s validation failures are caught below:
    a lock that cannot be acquired, or an override file that exists but
    cannot be read, means this skill's actual customization was never
    captured at all — continuing past that and letting `export_store.py`
    finish successfully would produce exactly the silently-incomplete
    export this feature exists to refuse, the same way a symlink under
    `memory/` stops the export rather than being quietly skipped. Letting
    the exception propagate here reaches `export_store.py`'s own
    surrounding `except BaseException`, which discards the whole staging
    directory and re-raises — the export either has everything, or does
    not exist.
    """
    results: list[tuple[Report, str | None]] = []
    for name in sorted(set(_list_skill_names(root))
                       | set(_overridden_skill_names_strict(root))):
        with (_skill_lock_only(root, name) if locked else _skill_lock(root, name)):
            try:
                report = _check_one_skill(root, name)
            except UnicodeDecodeError as exc:
                # The one specific, tolerated exception `_check_one_skill`
                # can raise on malformed content, not a capture failure:
                # it fails to decode the override as UTF-8 for
                # validation, but that is real and belongs in the
                # report, and must not stop the bytes below from being
                # captured anyway via `surrogateescape` — export exists
                # to preserve what the user actually wrote, not only
                # what happens to validate cleanly. Anything else
                # `_check_one_skill` can raise (a permission error, a
                # symlink-containment refusal, a database error) is a
                # genuine capture failure and is deliberately NOT caught
                # here — see this function's own docstring.
                report = Report("error", name, f"{type(exc).__name__}: {exc}")
            if report is None:
                continue
            override_file = _safe_child(_overrides_dir(root), name, "SKILL.md")
            if _regular_file_exists(override_file):
                # Raw bytes via `surrogateescape`, not a strict UTF-8
                # decode: this round-trips losslessly back to the
                # exact original bytes on write, so a malformed or
                # non-UTF-8 override is still copied byte-for-byte
                # rather than silently omitted because it failed to
                # decode. A failure here (e.g. permission denied) is
                # exactly the capture failure this function's own
                # docstring says must abort the export, so it is left
                # to propagate rather than being caught into text=None.
                text = override_file.read_bytes().decode(
                    "utf-8", errors="surrogateescape")
            else:
                text = None
        results.append((report, text))
    return results


# ---------------------------------------------------------------------------
# Apply — one skill, one connection, one to three commits, start to finish
# ---------------------------------------------------------------------------


def _apply_one_skill(root: Path, skill_name: str) -> Report | None:
    # Everything below, including the connect, is inside this one skill's
    # own try/except and its own lock — a locked file, a corrupt or
    # unreadable database, or any other failure becomes this skill's own
    # report, never an exception that escapes the loop in
    # `apply_overrides()` and aborts every skill after this one, and
    # never something that can interleave with another process's own
    # claim-write-complete sequence for this exact skill.
    try:
        with _skill_lock(root, skill_name):
            conn = _connect(root)
            try:
                conn.execute("BEGIN IMMEDIATE")
                live_file = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
                if not live_file.is_file():
                    _rollback(conn)
                    override_file = _safe_child(
                        _overrides_dir(root), skill_name, "SKILL.md")
                    if override_file.is_file():
                        return Report(
                            "orphaned-override", skill_name,
                            "no shipped SKILL.md for this skill, but an "
                            "override for it still exists; nothing to "
                            "observe or apply")
                    return None
                live_text = live_file.read_text(encoding="utf-8")

                # A still-pending operation for this skill — whether
                # genuinely diverged or merely a different kind of
                # operation than this one — must block this skill before
                # anything below observes it, not merely once
                # `_claim_operation` is reached; see
                # `_pending_operation_verdict`'s own docstring for why.
                verdict = _pending_operation_verdict(
                    conn, skill_name, "apply", _sha256(live_text))
                if verdict is not None:
                    conn.execute("COMMIT")
                    return verdict

                _observe_if_new(conn, root, skill_name, live_text)
                override_file = _safe_child(_overrides_dir(root), skill_name, "SKILL.md")
                if not override_file.is_file():
                    # Forget a manifest only after live bytes passed the
                    # accepted-distribution check. Unknown edits must not
                    # erase recovery state.
                    live_hash = _sha256(live_text)
                    if not _is_own_write(conn, skill_name, live_hash):
                        conn.execute(
                            "DELETE FROM applied_overrides WHERE skill_name = ?",
                            (skill_name,))
                    conn.execute("COMMIT")
                    return None

                override_text = override_file.read_text(encoding="utf-8")
                reason = _validate_override_text(conn, root, skill_name, override_text)
                if reason:
                    conn.execute("COMMIT")  # validation only; no live write
                    return Report("skipped-invalid", skill_name, reason)

                fm = _frontmatter(override_text)
                based_on = fm["based_on_sha256"]
                latest = _latest_base(conn, skill_name)
                if latest is not None and based_on != latest:
                    # An accepted update changed the base. Preserve the
                    # live file and the user's edit until explicit rebase.
                    conn.execute("COMMIT")
                    return Report(
                        "skipped-stale", skill_name,
                        f"override was forked from a different shipped "
                        f"version (recorded {based_on[:12]}, latest known "
                        f"is {latest[:12]}); export the edit, then --remove "
                        "and --fork to rebase it; live content left untouched")

                kind, detail = "applied", "matches the shipped version it was forked from"
                before_hash = _sha256(live_text)
                after_hash = _sha256(override_text)
                if before_hash == after_hash:
                    conn.execute("COMMIT")
                    return Report(kind, skill_name, detail)

                op_id, reason = _claim_operation(conn, skill_name, "apply", before_hash, after_hash)
                if op_id is None:
                    _rollback(conn)
                    return Report("blocked", skill_name, reason)
                conn.execute("COMMIT")  # durable before the filesystem changes

                # No other process can be doing this same thing to this same
                # skill right now — this function holds that skill's own
                # lock for its entire duration, so the gap here is only ever
                # a gap against a crash of this same process, never against
                # a second claimant.
                _atomic_write(live_file, override_text)

                conn.execute("BEGIN IMMEDIATE")
                # Kept as insurance, not because a second claimant is
                # possible while this skill's lock is held: if it were ever
                # bypassed by a future change, this still refuses to record
                # a result that never happened rather than trusting a stale
                # local value.
                cur = conn.execute(
                    "UPDATE override_operations SET status = 'complete'"
                    " WHERE id = ? AND status != 'complete' AND expected_after_hash = ?",
                    (op_id, after_hash))
                if cur.rowcount == 0:
                    conn.execute("ROLLBACK")
                    return Report(
                        "error", skill_name,
                        "this skill's own operation record changed while "
                        "its lock was held, which should not be possible; "
                        "left untouched rather than trusting it")
                conn.execute(
                    "INSERT INTO applied_overrides(skill_name, applied_hash)"
                    " VALUES (?, ?)"
                    " ON CONFLICT(skill_name) DO UPDATE SET"
                    " applied_hash = excluded.applied_hash,"
                    " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (skill_name, after_hash))
                conn.execute("COMMIT")
                return Report(kind, skill_name, detail)
            except BaseException:
                _rollback(conn)
                raise
            finally:
                conn.close()
    except Exception as exc:
        # Caught here, not re-raised: this function processes exactly one
        # skill, and its failure must never abort or roll back a sibling
        # skill's already-committed work in the loop that calls it.
        return Report("blocked" if isinstance(exc, UnverifiedBase) else "error",
                      skill_name, f"{type(exc).__name__}: {exc}")


def apply_overrides(root: Path) -> list[Report]:
    """Validate and materialize every override, one skill at a time, each
    on its own connection and transaction — one skill's failure, however
    it fails, is isolated to that skill's own report."""
    names = sorted(set(_list_skill_names(root))
                   | set(_list_overridden_skill_names(root)))
    reports: list[Report] = []
    for name in names:
        report = _apply_one_skill(root, name)
        if report is not None:
            reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Fork
# ---------------------------------------------------------------------------


def fork_skill(root: Path, skill_name: str) -> Report:
    _validate_skill_name(skill_name)
    with _skill_lock(root, skill_name):
        conn = _connect(root)
        try:
            shipped = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
            if not shipped.is_file():
                return Report("skipped-unknown-skill", skill_name,
                              f"no shipped skill named {skill_name!r}")

            override_path = _safe_child(_overrides_dir(root), skill_name, "SKILL.md")

            # Both pending-operation checks below run before the
            # override-already-exists check that follows them, not
            # after — deliberately, even though neither one needs to
            # know whether an override file exists to answer. The exact
            # crash state a `--remove` leaves between restoring the live
            # file and unlinking the override file has the *old*
            # override file still physically present, so checking
            # existence first would hit `skipped-exists` — "edit it
            # directly" — without this function ever having seen the
            # pending remove hanging over that same file. A user editing
            # it on that advice would have their edits silently deleted
            # the moment reconciliation finishes that remove.
            conn.execute("BEGIN IMMEDIATE")
            live_text = shipped.read_text(encoding="utf-8")
            live_hash = _sha256(live_text)
            if _pending_operation_diverged(conn, skill_name, live_hash):
                # Live content matches neither a still-pending
                # operation's recorded starting point nor its intended
                # result — genuinely diverged, not this feature's own
                # write and not necessarily a fresh shipped version
                # either. `_is_own_write` below would correctly refuse
                # to recognize it as "ours", but the `else` branch would
                # then call `_observe_if_new` and record it as a trusted
                # new shipped base anyway, and the resulting fork would
                # promise an override the next `--apply` cannot actually
                # use while that row sits unresolved. Refuse instead.
                _rollback(conn)
                return Report(
                    "blocked", skill_name,
                    "a previous operation on this skill is still "
                    "unresolved, and the live content no longer matches "
                    "what it expected; run --check, investigate, and "
                    "clear it by hand before forking this skill again")

            pending = _pending_operation_row(conn, skill_name)
            if pending is not None and pending[0] != "apply":
                # A still-pending `remove` — landed or not, not
                # diverged (that case is already refused above) — must
                # block forking (or re-forking) this skill the same way
                # `_pending_operation_verdict` blocks apply/remove from
                # silently reusing a different kind of pending row:
                # unlike apply, fork never claims or touches this row at
                # all, but the override file at this path — a fresh one
                # this call is about to create, or an old one already
                # sitting here that `skipped-exists` below would
                # otherwise invite editing — can still be destroyed by
                # it. If the remove already landed, the next
                # reconciliation sees `op_type == "remove"` and
                # unconditionally unlinks whatever override file exists
                # at this exact path. If it has not landed, the next
                # `--apply` would refuse a fresh override anyway
                # (blocked by this same pending row), so reporting
                # `forked` here would promise something already
                # unusable. Either way, this must be resolved first —
                # reconciliation will finish a landed remove, or
                # `--remove` will retry one that has not.
                _rollback(conn)
                return Report(
                    "blocked", skill_name,
                    "a previous remove operation on this skill is still "
                    "unresolved; run --check to see it, then either let "
                    "reconciliation finish it (if its write already "
                    "landed) or re-run --remove (if it has not) before "
                    "forking this skill again — otherwise a newly forked "
                    "override could be silently deleted once that remove "
                    "is reconciled, or could never be applied while it "
                    "stays pending")

            if _regular_file_exists(override_path):
                _rollback(conn)
                return Report("skipped-exists", skill_name,
                              "an override for this skill already exists; edit "
                              "it directly or --remove it first")

            if _is_own_write(conn, skill_name, live_hash):
                # Live content is this feature's own previously applied
                # override, not genuine shipped content — its override
                # file was deleted by hand while the applied record (or a
                # crashed apply's still-pending record) survived. Forking
                # "from" it would embed its own hash as
                # `based_on_sha256`, which was deliberately never
                # recorded in `base_observations` for this skill (that is
                # exactly what "not genuine shipped content" means), so
                # the very next `--apply` would refuse the new override
                # as based on something never observed. Fork from the
                # latest retained shipped base instead.
                _rollback(conn)
                retained_hash = _latest_base(conn, skill_name)
                source_text = _base_text(root, retained_hash) if retained_hash else None
                if source_text is None:
                    return Report(
                        "skipped-invalid", skill_name,
                        "the currently shipped content for this skill is "
                        "this feature's own previously applied override, "
                        "with no retained shipped base left to fork from "
                        "instead; run --remove to restore genuine shipped "
                        "content first")
            else:
                _observe_if_new(conn, root, skill_name, live_text)
                # Committed before the override file is ever written, not
                # in the same transaction as that write: a crash between
                # them would otherwise leave a `based_on_sha256` on disk
                # that nothing durably recorded as observed, and no way
                # back — `--apply` would refuse it as never-observed, and
                # a rerun of `--fork` would refuse because the file
                # already exists.
                conn.execute("COMMIT")
                source_text = live_text

            if not FRONTMATTER.match(source_text):
                return Report("skipped-invalid", skill_name,
                              "the shipped skill has no frontmatter block to "
                              "fork from")

            base_hash = _sha256(source_text)
            # Always the freshly computed hash of the source text, never a
            # `based_on_sha256` it happened to already contain — trusting
            # that value would let stale or foreign content decide what
            # this fork claims to be based on.
            if "based_on_sha256" in _frontmatter(source_text):
                forked = re.sub(
                    r"(?m)^based_on_sha256:.*$",
                    f"based_on_sha256: {base_hash}", source_text, count=1)
            else:
                forked = FRONTMATTER.sub(
                    lambda m: f"---\n{m.group(1)}\nbased_on_sha256: {base_hash}\n---\n",
                    source_text, count=1)
            # Outside any transaction, and safe to be: the observation
            # this write depends on is already durable, and a crash here
            # just leaves no override file yet — trivially retryable by
            # running `--fork` again, with nothing to reconcile.
            _atomic_write(override_path, forked)
            return Report("forked", skill_name,
                          f"based on the latest known shipped version "
                          f"({base_hash[:12]}); edit "
                          f"{override_path} and it will be applied on the next run")
        except BaseException:
            _rollback(conn)
            raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Remove — only ever touches a skill that actually has an override, and
# durably records its intent before either filesystem change.
# ---------------------------------------------------------------------------


def remove_override(root: Path, skill_name: str) -> Report:
    _validate_skill_name(skill_name)
    # This skill's own pending operations first, not just at the CLI
    # layer: `_remove_override_core`'s gate recognizes a still-pending
    # apply whose expected-after hash matches live content as active
    # state to restore, but `_claim_operation` inside it still refuses
    # to claim a new "remove" while that same row sits unresolved — its
    # `expected_before_hash` is the pre-crash content, not the live
    # override. Without reconciling here, only `main()`'s CLI path
    # (which already calls `reconcile_skill` before dispatching to
    # `--remove`) would actually be able to undo that crash state; this
    # function itself, called directly, would report `blocked` for
    # exactly the case its own gate was extended to handle. Scoped to
    # just this skill, same reasoning as `reconcile_skill`'s own
    # docstring: an unrelated skill's held lock must never delay a
    # request that was never about it.
    reconcile_skill(root, skill_name)
    with _skill_lock(root, skill_name):
        return _remove_override_core(root, skill_name)


def _remove_override_core(root: Path, skill_name: str) -> Report:
    """The actual work, assuming the caller already holds this skill's own
    lock (only `remove_override` calls this now — `reset.py`'s
    restoration pass uses the separate, deliberately narrower
    `_restore_live_file_only` under the coarser global exclusive lock
    instead, see `restore_all_for_reset_locked`).

    Proceeds when there is customized state to undo for this skill — an
    override *file*, a completed `applied_overrides` row, or a still-
    pending `apply` operation whose expected result matches live content
    (the same crash window `_is_own_write` exists to recognize) — and
    refuses otherwise. An override file is the ordinary signal, but it is
    not the only one: a file deleted by hand instead of through
    `--remove` leaves live content customized with only a database row
    left to show for it, and `--remove` must still be able to undo that,
    not just report success while leaving it live. What it must not do is
    restore a skill nobody ever customized just because cron observed its
    shipped content and `_latest_base` can therefore answer — that would
    roll back a skill this command was never asked to touch.
    """
    conn = _connect(root)
    try:
        override_path = _safe_child(_overrides_dir(root), skill_name, "SKILL.md")
        live_file = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
        has_override_file = _regular_file_exists(override_path)
        live_text = (live_file.read_text(encoding="utf-8")
                    if _regular_file_exists(live_file) else None)

        # Checked before the "is there even customized state to undo"
        # gate right below, not merely before `_observe_if_new` further
        # down: with the override file gone and no applied row, diverged
        # live content also fails `_is_own_write`'s check inside that
        # gate (correctly — diverged content is not this feature's own
        # write), so without this the gate itself would return
        # `skipped-no-override` first, reporting nothing to do while a
        # genuinely unresolved, diverged operation still sits on this
        # skill. `remove_override()`'s own preliminary `reconcile_skill`
        # call may already have reported this as diverged, but it does
        # not stop `_remove_override_core` from running anyway.
        if live_text is not None and _pending_operation_diverged(
                conn, skill_name, _sha256(live_text)):
            return Report(
                "blocked", skill_name,
                "a previous operation on this skill is still unresolved, "
                "and the live content no longer matches what it "
                "expected; run --check, investigate, and clear it by "
                "hand before this skill is touched again automatically")

        if not has_override_file:
            has_applied_row = conn.execute(
                "SELECT 1 FROM applied_overrides WHERE skill_name = ?",
                (skill_name,)).fetchone() is not None
            has_pending_apply = (
                live_text is not None
                and _is_own_write(conn, skill_name, _sha256(live_text)))
            if not (has_applied_row or has_pending_apply):
                return Report("skipped-no-override", skill_name,
                              "this skill has no override and no applied "
                              "record; nothing to remove")

        # Validate provenance before changing the live file or its history.
        if live_text is not None:
            verdict = _pending_operation_verdict(
                conn, skill_name, "remove", _sha256(live_text))
            if verdict is not None:
                return verdict
            conn.execute("BEGIN IMMEDIATE")
            _observe_if_new(conn, root, skill_name, live_text)
            conn.execute("COMMIT")

        # Only a skill in the accepted distribution has a current base.
        # A historical observation cannot resurrect a retired skill.
        latest_hash = _latest_base(conn, skill_name)
        if latest_hash is None:
            return Report("skipped-no-base", skill_name,
                          "no retained base for this skill; nothing to "
                          "restore, override left in place")
        base_text = _base_text(root, latest_hash)
        if base_text is None:
            return Report("skipped-missing-base", skill_name,
                          f"the retained base {latest_hash[:12]} is missing "
                          "or corrupt; override left in place rather than "
                          "leaving the skill with nothing usable")

        conn.execute("BEGIN IMMEDIATE")
        before_hash = (_sha256(live_file.read_text(encoding="utf-8"))
                      if _regular_file_exists(live_file) else "")
        op_id, reason = _claim_operation(conn, skill_name, "remove", before_hash, latest_hash)
        if op_id is None:
            _rollback(conn)
            return Report("blocked", skill_name, reason)
        conn.execute("COMMIT")  # durable before either filesystem change

        # This skill's own lock is held for the whole function, so
        # both idempotent writes below are only ever redone against a
        # crash of this same process, never raced by a second one.
        _atomic_write(live_file, base_text)
        if _regular_file_exists(override_path):
            override_path.unlink()
            _fsync_dir(override_path.parent)

        conn.execute("BEGIN IMMEDIATE")
        # Insurance, not a live race guard — see the matching comment
        # in `_apply_one_skill`.
        cur = conn.execute(
            "UPDATE override_operations SET status = 'complete'"
            " WHERE id = ? AND status != 'complete' AND expected_after_hash = ?",
            (op_id, latest_hash))
        if cur.rowcount == 0:
            conn.execute("ROLLBACK")
            return Report(
                "error", skill_name,
                "this skill's own operation record changed while its "
                "lock was held, which should not be possible; left "
                "untouched rather than trusting it")
        conn.execute(
            "DELETE FROM applied_overrides WHERE skill_name = ?", (skill_name,))
        conn.execute("COMMIT")
        return Report("removed", skill_name,
                      f"restored to {latest_hash[:12]}, the latest known "
                      "shipped version")
    except BaseException:
        _rollback(conn)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Startup reconciliation — one row, one connection, one to two commits
# ---------------------------------------------------------------------------


def _reconcile_one(root: Path, op_id: int) -> Report | None:
    """Re-reads this row's current state itself, inside its own
    transaction and its own skill's lock, rather than trusting a value
    `reconcile()` merely listed earlier — a crash could have completed it
    since, or (before this row's skill name is even known, so its lock
    cannot be held yet) it could have been deleted outright. Returns
    `None` when there is nothing left to reconcile, which is not the same
    as nothing having happened.
    """
    label = f"op#{op_id}"  # until a real skill name is known and trusted
    try:
        # The global lock in shared mode, even for this read-only lookup
        # — `_connect()` is not read-only itself: it creates
        # `workspace/skill-overrides/` and the database file if either
        # is missing. Without holding at least the shared barrier here,
        # this call could recreate that tree while `reset.py` holds the
        # lock exclusively and is mid-way through deleting it, letting a
        # reset that reports everything gone leave skill-overrides state
        # behind because reconciliation raced it outside the one barrier
        # every other mutating path agrees to wait on.
        with _global_lock(root, exclusive=False):
            conn = _connect(root)
            try:
                row = conn.execute(
                    "SELECT skill_name FROM override_operations WHERE id = ?",
                    (op_id,)).fetchone()
            finally:
                conn.close()
    except Exception as exc:
        return Report("reconciled-error", label, f"{type(exc).__name__}: {exc}")
    if row is None:
        return None
    skill_name = row[0]
    try:
        _validate_skill_name(skill_name)
    except InvalidSkillName as exc:
        # A row whose own `skill_name` column isn't a name this module
        # could ever have written itself — corrupt, not merely stale.
        # Refuse before it is ever used to build a lock path.
        return Report("reconciled-error", label, str(exc))

    try:
        return _reconcile_one_locked(root, op_id, skill_name)
    except Exception as exc:
        # Covers a lock-acquisition failure itself (e.g. an unwritable
        # locks directory) as well as anything `_reconcile_one_locked`
        # did not already turn into a Report — this row's own problem,
        # never something that should abort reconciling any other row.
        return Report("reconciled-error", skill_name, f"{type(exc).__name__}: {exc}")


def _reconcile_one_locked(root: Path, op_id: int, skill_name: str) -> Report | None:
    with _skill_lock(root, skill_name):
        conn = _connect(root)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT skill_name, op_type, status, expected_before_hash,"
                " expected_after_hash FROM override_operations WHERE id = ?",
                (op_id,)).fetchone()
            if row is None or row[2] == "complete":
                # Resolved (or its row deleted outright) since this op_id
                # was listed, by whichever process held this skill's lock
                # just before this one acquired it.
                conn.execute("COMMIT")
                return None
            # Re-checked, not merely reused, even though `skill_name` is
            # never actually updated once a row exists (`_claim_operation`
            # only ever reuses a row already scoped to the skill calling
            # it) — insurance against that invariant ever changing without
            # this lock's own scope being updated to match.
            if row[0] != skill_name:
                conn.execute("COMMIT")
                return Report(
                    "reconciled-error", skill_name,
                    f"this row now belongs to {row[0]!r}, not the skill "
                    "whose lock this reconcile pass is holding; left "
                    "untouched")
            op_type, _status, before_hash, after_hash = row[1], row[2], row[3], row[4]

            try:
                live_file = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
            except UnsafePath as exc:
                _rollback(conn)
                return Report("reconciled-error", skill_name, str(exc))

            try:
                live_mode = live_file.stat().st_mode
            except FileNotFoundError:
                # The only condition treated as a confirmed absence — not
                # `is_file()`/`exists()` returning False, which `stat`
                # denied or any other unreadable state can also produce,
                # and which is not the same as "gone" (below).
                live_hash = ""
                live_confirmed_absent = True
            except OSError as exc:
                _rollback(conn)
                return Report("reconciled-error", skill_name,
                             f"{type(exc).__name__}: {exc}")
            else:
                live_confirmed_absent = False
                if stat.S_ISREG(live_mode):
                    live_hash = _sha256(live_file.read_text(encoding="utf-8"))
                else:
                    # A directory, a device, something this module never
                    # wrote. Deliberately unequal to any real sha256 so it
                    # can never be mistaken for a landed write, and never
                    # treated as "gone" either — that distinction is
                    # exactly what separates a confirmed absence (safe to
                    # abandon, below) from anything else unexpected (never
                    # abandoned, always surfaced as diverged instead).
                    live_hash = "\0anomalous"

            if live_hash == after_hash:
                # The write landed. Finish whatever side effect a crash could
                # have skipped between that write and this operation's own
                # completion commit — reconcile is the only thing that will
                # ever come back to do this, since nothing re-queues a
                # finished write.
                if op_type == "remove":
                    override_path = _safe_child(
                        _overrides_dir(root), skill_name, "SKILL.md")
                    if _regular_file_exists(override_path):
                        override_path.unlink()
                        _fsync_dir(override_path.parent)
                    conn.execute(
                        "DELETE FROM applied_overrides WHERE skill_name = ?",
                        (skill_name,))
                else:
                    conn.execute(
                        "INSERT INTO applied_overrides(skill_name, applied_hash)"
                        " VALUES (?, ?)"
                        " ON CONFLICT(skill_name) DO UPDATE SET"
                        " applied_hash = excluded.applied_hash,"
                        " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                        (skill_name, after_hash))
                conn.execute(
                    "UPDATE override_operations SET status = 'complete'"
                    " WHERE id = ?", (op_id,))
                conn.execute("COMMIT")
                return Report("reconciled-complete", skill_name,
                              "the intended write had already landed; finished "
                              "what a crash left undone")
            elif live_hash == before_hash:
                conn.execute("COMMIT")
                if op_type == "apply":
                    detail = ("the write never happened; the next scheduled "
                              "apply tick will redo it on its own")
                else:
                    detail = ("the write never happened; nothing retries a "
                              "remove on a schedule — run --remove on this "
                              "skill again to redo it")
                return Report("reconciled-retry", skill_name, detail)
            elif live_confirmed_absent:
                # Not "changed to something unrecognized" — gone entirely.
                # There is nothing left here for a human to look at or for
                # this row to protect by staying pending forever; clearing
                # it is what lets a later --remove on this now-orphaned
                # skill (which restores the last known base into a fresh
                # directory, by design) proceed instead of being refused
                # by a record of a write that can no longer have happened
                # either way.
                conn.execute(
                    "UPDATE override_operations SET status = 'complete'"
                    " WHERE id = ?", (op_id,))
                conn.execute("COMMIT")
                return Report("reconciled-abandoned", skill_name,
                              "the shipped skill no longer exists; the "
                              "pending operation record for it has been "
                              "cleared rather than left blocking it forever")
            else:
                conn.execute("COMMIT")
                return Report("reconciled-diverged", skill_name,
                              "live content matches neither the expected "
                              "before nor after state — something outside "
                              "this module changed it since; left untouched, "
                              "and this skill is blocked from automated "
                              "apply/remove until it is resolved")
        except Exception as exc:
            _rollback(conn)
            return Report("reconciled-error", skill_name, f"{type(exc).__name__}: {exc}")
        finally:
            conn.close()


def _reconcile_op_ids(root: Path, skill_name: str | None) -> list[int] | Report:
    """The pending op ids to reconcile — every one, or just those for one
    skill. Returns a `Report` instead of raising if the listing itself
    fails, since a locked or corrupt database must still surface as
    something `main()` can report and exit nonzero for, not an exception
    that aborts before any skill is touched.

    The global lock in shared mode around the whole thing, same
    reasoning as `_reconcile_one`'s matching comment: `_connect()`
    recreates `workspace/skill-overrides/` and the database file if
    either is missing, and this is the very first thing either
    `reconcile()` or `reconcile_skill()` does — without the barrier
    here, this call alone could race `reset.py`'s exclusive hold and
    recreate the tree reset is still in the middle of deleting.
    """
    try:
        with _global_lock(root, exclusive=False):
            conn = _connect(root)
            try:
                if skill_name is None:
                    rows = conn.execute(
                        "SELECT id FROM override_operations"
                        " WHERE status != 'complete'").fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id FROM override_operations"
                        " WHERE status != 'complete' AND skill_name = ?",
                        (skill_name,)).fetchall()
                return [row[0] for row in rows]
            finally:
                conn.close()
    except Exception as exc:
        return Report("error", skill_name or "reconcile",
                      f"{type(exc).__name__}: {exc}")


def reconcile(root: Path) -> list[Report]:
    """Resolve every `override_operations` row left non-`complete`, one row
    at a time on its own connection and its own skill's lock — one row's
    failure to reconcile never blocks reconciling the rest."""
    return _reconcile_op_ids_to_reports(root, _reconcile_op_ids(root, None))


def reconcile_skill(root: Path, skill_name: str) -> list[Report]:
    """The same as `reconcile()`, scoped to one skill's own pending rows.

    `--fork <skill>`/`--remove <skill>` only need this skill's own
    bookkeeping resolved before proceeding — reconciling every other
    skill's rows first, the way the bare CLI's full `reconcile()` does,
    means an unrelated skill's held lock could delay a request that was
    never about that skill at all. A scheduled `--apply` tick still runs
    the full sweep, so nothing goes permanently unreconciled.
    """
    return _reconcile_op_ids_to_reports(root, _reconcile_op_ids(root, skill_name))


def _reconcile_op_ids_to_reports(root: Path, op_ids: list[int] | Report) -> list[Report]:
    if isinstance(op_ids, Report):
        return [op_ids]
    reports = []
    for op_id in op_ids:
        try:
            report = _reconcile_one(root, op_id)
        except Exception as exc:
            # `_reconcile_one` already catches everything it can attribute
            # to a skill; this is the last line of defense against
            # anything that still escapes it, so one row's surprise never
            # stops the rest of this loop from running.
            report = Report("reconciled-error", f"op#{op_id}",
                            f"{type(exc).__name__}: {exc}")
        if report is not None:
            reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Reset support — `reset.py` deletes `workspace/skill-overrides/` outright,
# so it needs all three of these: restoring every live customization first
# (otherwise the words stay live and untracked, contradicting "everything
# is gone"); a fast, friendly, best-effort check for the ordinary case of
# running underneath a tick that is obviously already in flight; and the
# real barrier — the global lock's exclusive mode — actually held across
# restoration AND deletion as one epoch, not just around the deletion,
# since anything that ran between the two could create or apply a new
# override that restoration never saw and deletion would then destroy
# unrestored.
# ---------------------------------------------------------------------------


def _list_applied_skill_names(root: Path) -> list[str]:
    """Skills with an `applied_overrides` row — a signal restoration has
    to catch that neither `_list_skill_names` nor
    `_list_overridden_skill_names` can: an override file deleted by hand
    instead of through `--remove` leaves live content still customized
    with only this row left to show for it.

    Deliberately does not degrade a genuine access failure to "found
    nothing" the way `_list_skill_names`'s lenient, top-level listing
    does for `--check`/`--apply`: this is only ever called from
    `restore_all_for_reset_locked`, and a reset that could not actually
    determine which skills have an applied row must not silently proceed
    as if none did — only `FileNotFoundError` on the database file
    itself, and only through it never having been created, means "no
    applied skills"; a database that exists but cannot be opened or
    queried propagates instead.
    """
    db_path = _db_path(root)
    if not _regular_file_exists(db_path):
        return []
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return sorted(r[0] for r in
                     conn.execute("SELECT skill_name FROM applied_overrides").fetchall())
    finally:
        conn.close()


def _list_pending_operation_skill_names(root: Path) -> list[str]:
    """Skills with a still-`pending` row in `override_operations` — the
    same signal `_is_own_write` checks for the specific crash window
    between an apply's file write and its completion commit, which
    leaves an override live with no override file and no
    `applied_overrides` row, and only this row left to show for it.

    Read straight from the database rather than derived from any
    filesystem listing, deliberately: the crash state this exists to
    catch can coincide with exactly the kind of directory that cannot be
    enumerated (a permissions oddity on `skills/` or `overrides/`, not
    merely a hypothetical — `iterdir()` and a direct `stat()` on a known
    path are allowed to disagree about what is readable). Restoration's
    candidate list must not depend on being able to list either
    directory to find this skill; this sidesteps that entirely — and, by
    the same reasoning as `_list_applied_skill_names`, must not depend on
    being able to open or query the database either. Only the database
    file never having been created at all means "nothing pending";
    anything else propagates.
    """
    db_path = _db_path(root)
    if not _regular_file_exists(db_path):
        return []
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return sorted(r[0] for r in conn.execute(
            "SELECT DISTINCT skill_name FROM override_operations"
            " WHERE status != 'complete'").fetchall())
    finally:
        conn.close()


def _restore_live_file_only(root: Path, skill_name: str) -> Report:
    """Restore this feature's live write from an accepted base during reset.

    Preserve live content that another writer already installed. Leave
    overrides, manifests and history intact until the caller accounts for
    every skill and deletes the state tree under the global lock. A failure can
    leave an earlier live skill restored, but deletes no edits.
    """
    override_path = _safe_child(_overrides_dir(root), skill_name, "SKILL.md")
    live_file = _safe_child(_skills_dir(root), skill_name, "SKILL.md")
    conn = _connect(root)
    try:
        has_override_file = _regular_file_exists(override_path)
        live_text = (live_file.read_text(encoding="utf-8")
                    if _regular_file_exists(live_file) else None)

        # Checked before anything else, including the "is there even
        # anything to restore" gate right below: a still-pending
        # operation whose live content matches neither its recorded
        # starting point nor its intended result is genuinely diverged,
        # not merely uncustomized. Falling through to that gate would
        # read as "skipped-no-override" the moment the override file and
        # applied row also happen to be gone (`_is_own_write` correctly
        # refuses to recognize diverged content as this feature's own),
        # letting reset delete the one row that explains the divergence
        # while reporting the skill successfully restored — or, if the
        # override file is still present, letting `_observe_if_new`
        # below record the diverged content as a trusted new base before
        # restoring straight over it. Either way, reset must refuse this
        # skill outright rather than guess.
        if live_text is not None and _pending_operation_diverged(
                conn, skill_name, _sha256(live_text)):
            return Report(
                "blocked", skill_name,
                "a previous operation on this skill is still unresolved, "
                "and the live content no longer matches what it "
                "expected; reset refuses to touch this skill "
                "automatically — run --check to see it, resolve it by "
                "hand, and try again")

        if not has_override_file:
            has_applied_row = conn.execute(
                "SELECT 1 FROM applied_overrides WHERE skill_name = ?",
                (skill_name,)).fetchone() is not None
            # A crash landing between apply's file write and its
            # completion commit leaves exactly this: no override file (it
            # was never written in that mode, or was deleted by hand
            # afterward) and no applied row, but live content that is
            # still this feature's own write per a still-pending `apply`
            # operation. Missing this case here would let that customized
            # content sit live forever the moment its override file
            # happened to be gone too — reset would report it restored
            # (because there is nothing left to gate on) while never
            # having touched it.
            has_pending_apply = (
                live_text is not None
                and _is_own_write(conn, skill_name, _sha256(live_text)))
            if not (has_applied_row or has_pending_apply):
                return Report("skipped-no-override", skill_name,
                              "this skill has no override and no applied "
                              "record; nothing to restore")

        if (live_text is not None
                and not _is_own_write(
                    conn, skill_name, _sha256(live_text))):
            # Another writer has already replaced the applied override. Reset
            # does not need an accepted base to preserve bytes this feature
            # did not write, and refusing here would also prevent deletion of
            # the ledger, memory, and the override state itself after an
            # otherwise ordinary bare profile update. A genuinely diverged
            # pending operation was already rejected above, before this safe
            # cancellation path.
            return Report(
                "preserved-live", skill_name,
                "live content is not this feature's recorded write; left it "
                "unchanged while reset removes the tracked override state")

        if live_text is not None:
            conn.execute("BEGIN IMMEDIATE")
            _observe_if_new(conn, root, skill_name, live_text)
            conn.execute("COMMIT")

        latest_hash = _latest_base(conn, skill_name)
        if latest_hash is None:
            return Report("skipped-no-base", skill_name,
                          "no retained base for this skill; nothing to "
                          "restore, override left in place")
        base_text = _base_text(root, latest_hash)
        if base_text is None:
            return Report("skipped-missing-base", skill_name,
                          f"the retained base {latest_hash[:12]} is missing "
                          "or corrupt; override left in place rather than "
                          "leaving the skill with nothing usable")

        _atomic_write(live_file, base_text)
        return Report("removed", skill_name,
                      f"restored to {latest_hash[:12]}, the latest known "
                      "shipped version")
    except BaseException:
        _rollback(conn)
        raise
    finally:
        conn.close()


def restore_all_for_reset_locked(root: Path) -> list[Report]:
    """Restore every currently active override's live file to its latest
    known shipped content, touching nothing else — see
    `_restore_live_file_only`'s own docstring for why cleanup of the
    override files and bookkeeping themselves is deliberately left to the
    bulk deletion that follows a fully successful restoration pass, not
    done here per skill.

    Must be called from inside `with exclusive_lock_for_reset(root):`, and
    only from there — this uses `_skill_lock_only` per skill rather than
    the ordinary `_skill_lock`, specifically so it never tries to
    re-acquire the global lock a second time while the caller already
    holds it exclusively (which would deadlock against itself). Holding
    the exclusive lock across this entire function, not just around the
    deletion that follows it in `reset.py`, is what closes the gap a
    merely-sequential "restore, then separately lock and delete" would
    leave: nothing else can create or apply a new override in between,
    because nothing else can even begin claiming a skill's lock until
    this whole epoch — restoration and deletion together — ends.

    One skill's failure is caught and reported, not raised — a crash
    restoring skill B must never abort skill A's already-successful
    restoration, or leave reset itself dying with a traceback mid-epoch.
    """
    candidates = sorted(set(_list_skill_names(root))
                        | set(_list_overridden_skill_names(root))
                        | set(_list_applied_skill_names(root))
                        | set(_list_pending_operation_skill_names(root)))
    reports = []
    for name in candidates:
        try:
            _validate_skill_name(name)
            with _skill_lock_only(root, name):
                reports.append(_restore_live_file_only(root, name))
        except Exception as exc:
            reports.append(Report("error", name, f"{type(exc).__name__}: {exc}"))
    return reports


def refuse_if_busy(root: Path) -> str | None:
    """A fast, friendly, best-effort check for a skill whose lock is
    currently held by another process — not the actual guarantee. A new
    operation can still start in the gap between this check and whatever
    runs after it; the real barrier is `exclusive_lock_for_reset`, which
    this only gives the caller an early, non-blocking way to avoid
    reaching for most of the time.
    """
    lock_dir = _locks_dir(root)
    if not lock_dir.is_dir() or lock_dir.is_symlink():
        return None
    for name in sorted(set(_list_skill_names(root))
                       | set(_list_overridden_skill_names(root))):
        lock_path = _safe_child(lock_dir, f"{name}.lock")
        if not lock_path.is_file():
            continue
        fd = os.open(lock_path, os.O_RDONLY)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                return name
        finally:
            os.close(fd)
    return None


def exclusive_lock_for_reset(root: Path):
    """The real barrier: exclusive mode of the same global lock every
    ordinary operation holds in shared mode through `_skill_lock`.
    Acquiring this blocks until every currently-running apply/remove/fork
    has finished and released its own shared hold, and once held, blocks
    any new one from starting — until this is released, nothing can even
    begin claiming a skill's own lock, which is what makes deleting the
    tree those locks live in safe. A context manager; use with `with`.
    """
    return _global_lock(root, exclusive=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _report_or_error(fn, root: Path, skill_name: str) -> Report:
    """Runs a single-skill CLI command and turns any exception it raises
    — an invalid name, a lock or database failure, anything — into a
    Report instead of an uncaught traceback. Without this, a typo like
    `--remove ../../x` printed neither the findings JSON nor the wake
    gate, which a scheduler or a script parsing this command's output
    cannot distinguish from the process never having run at all.
    """
    try:
        return fn(root, skill_name)
    except Exception as exc:
        return Report("blocked" if isinstance(exc, UnverifiedBase) else "error",
                      skill_name, f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Apply, check, fork, or remove a shipped skill's user "
                    "override.",
        # A mutating default command should not let a typo'd prefix like
        # `--a` silently resolve to `--apply` through argparse's ordinary
        # abbreviation matching.
        allow_abbrev=False)
    group = ap.add_mutually_exclusive_group(required=False)
    group.add_argument("--check", action="store_true",
                       help="report what --apply would do, write nothing")
    group.add_argument("--apply", action="store_true",
                       help="validate and apply every override (default)")
    group.add_argument("--fork", metavar="SKILL",
                       help="start an override from the shipped copy")
    group.add_argument("--remove", metavar="SKILL",
                       help="delete an override and restore the latest base")
    group.add_argument("--record-distribution", metavar="PROFILE_SOURCE", type=Path,
                       help="accept shipped bases from the reviewed recipe source")
    group.add_argument("--restore", metavar="BUNDLE", type=Path,
                       help="restore override state from a versioned recovery bundle")
    args = ap.parse_args(argv)

    root = profile_root()

    if args.record_distribution or args.restore:
        try:
            if args.record_distribution:
                reports = record_distribution(root, args.record_distribution)
            else:
                from skill_override_bundle import restore_bundle
                restore_bundle(root, args.restore)
                reports = [Report("restored", "*", "override state restored; live skills unchanged")]
        except Exception as exc:
            reports = [Report("error", "*", f"{type(exc).__name__}: {exc}")]
    elif args.check:
        # No reconcile() here: reconcile can repair this feature's own
        # bookkeeping (and, for a completed remove, delete an orphaned
        # override file), which is more than --check's "write nothing"
        # promise allows.
        reports = check_overrides(root)
    elif args.fork:
        # Scoped to just this skill's own pending rows, not the whole
        # profile's — an unrelated skill's held lock must never delay a
        # request that was never about that skill (see
        # `reconcile_skill`'s own docstring).
        reports = list(reconcile_skill(root, args.fork))
        reports.append(_report_or_error(fork_skill, root, args.fork))
    elif args.remove:
        reports = list(reconcile_skill(root, args.remove))
        reports.append(_report_or_error(remove_override, root, args.remove))
    else:
        reports = list(reconcile(root))
        reports.extend(apply_overrides(root))

    print(json.dumps({"findings": [
        {"kind": r.kind, "skill": r.skill, "detail": r.detail} for r in reports]},
        indent=2))
    # None of these four operations involve judgment, so the scheduled tick
    # never needs an agent turn — same contract as retention.py's gate.
    print(json.dumps({"wakeAgent": False}))
    return 1 if any(r.kind in PROBLEM_KINDS for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
