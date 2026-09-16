# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cooperating memory readers and writers share one stable lock inode."""

from __future__ import annotations

import contextlib
import contextvars
import fcntl
import functools
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import sys

from _db import ledger_path

_held = contextvars.ContextVar("memory_lock", default=None)
READ_GUARDS = {}
MANAGED_TYPES = {"projects", "patterns", "concepts"}
PAGE_TYPES = MANAGED_TYPES | {"people", "attention", "goals"}
UNFINISHED = "('prepared','applying','blocked_diverged')"


class MemoryBlocked(RuntimeError):
    """A pending operation or incompatible runtime prevents a coherent read."""


class MemoryConflict(ValueError):
    """The observed bytes or requested scope do not permit this operation."""


def digest(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def workspace() -> Path:
    return ledger_path().parent.parent


def validate_local(path: Path) -> None:
    """Reject indirection in existing components, including dangling links."""
    path = path.absolute()
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            # macOS exposes temporary directories through these OS-owned
            # root aliases. No profile/workspace component is exempted.
            if sys.platform == "darwin" and str(part) in {"/var", "/tmp"} and str(part.resolve()) == "/private" + str(part):
                continue
            raise MemoryConflict("symlink in memory resource path")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise MemoryConflict("unexpected hard link in memory resource path")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise MemoryConflict("non-regular memory resource")


def path_key(relative: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", relative).casefold()


def validate_database(path: Path) -> None:
    validate_local(path)
    for suffix in ("-journal", "-wal", "-shm"):
        validate_local(path.with_name(path.name + suffix))


def target(relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise MemoryConflict("memory path must be a relative POSIX path")
    parts = PurePosixPath(relative).parts
    if not parts or relative != "/".join(parts) or any(p in (".", "..") for p in parts):
        raise MemoryConflict("non-canonical memory path")
    if relative not in {"index.md", "log.md"}:
        project = (len(parts) == 3 and parts[0] == "projects"
                   and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", parts[1])
                   and parts[2] in {parts[1] + ".md", "log.md", "log.archive.md"})
        if not project and (len(parts) != 2 or parts[0] not in PAGE_TYPES):
            raise MemoryConflict("undeclared memory resource type")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.md", parts[-1]):
            raise MemoryConflict("unsupported memory filename")
    path = workspace() / "memory" / relative
    validate_local(path)
    return path


def read_bytes(path: Path) -> bytes | None:
    validate_local(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MemoryConflict("memory resource is not an unlinked regular file")
        return stream.read()


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdirs(path: Path) -> None:
    validate_local(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for current in reversed(missing):
        current.mkdir(mode=0o700, exist_ok=True)
        validate_local(current)
        fsync_directory(current.parent)


def clean_temporary(relative: str, token: str, expected: bytes | None) -> None:
    """Reclaim only this journal step's reserved temporary resource.

    A death between link() and unlink() leaves two names for one inode. Remove
    the known temporary name before applying the ordinary hard-link refusal.
    A partial temporary write is disposable only when it is an exact prefix
    of the frozen after-image, private, and owned by this process's user.
    """
    if not re.fullmatch(r"[a-f0-9-]+", token):
        raise ValueError("invalid journal temporary token")
    if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise MemoryConflict("temporary path escapes memory")
    path = workspace() / "memory" / relative
    validate_local(path.parent)
    temp = path.parent / (".memory-" + token)
    try:
        info = temp.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise MemoryConflict("reserved memory temporary file is not private and regular")
    fd = os.open(temp, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read()
    if expected is None or not expected.startswith(data):
        raise MemoryConflict("reserved memory temporary file diverged")
    if info.st_nlink == 2:
        live = path.lstat()
        if (live.st_dev, live.st_ino) != (info.st_dev, info.st_ino) or data != expected:
            raise MemoryConflict("unexpected temporary hard link")
    elif info.st_nlink != 1:
        raise MemoryConflict("unexpected temporary hard links")
    temp.unlink()
    fsync_directory(path.parent)


def replace(relative: str, before: bytes | None, after: bytes | None, *, token: str) -> None:
    """Compare again immediately before the atomic effect; never clobber creates."""
    path = target(relative)
    if read_bytes(path) != before:
        raise MemoryConflict("file diverged before replacement")
    if before == after:
        return
    mkdirs(path.parent)
    if after is None:
        if read_bytes(path) != before:
            raise MemoryConflict("file diverged before removal")
        path.unlink()
        fsync_directory(path.parent)
        return
    temp = path.parent / (".memory-" + token)
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if read_bytes(path) != before:
            raise MemoryConflict("file diverged before replacement")
        if before is None:
            # link is an atomic no-clobber publication, including on POSIX
            # filesystems whose rename operation would replace a destination.
            os.link(temp, path, follow_symlinks=False)
            temp.unlink()
        else:
            os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def memory_lock(*, exclusive=False, root=None):
    root = root or workspace()
    lock_path = root / ".memory-operations.lock"
    held = _held.get()
    if held:
        if held[0] != lock_path or (exclusive and not held[1]):
            raise RuntimeError("memory lock upgrade or cross-profile nesting refused")
        yield
        return
    mkdirs(root)
    validate_local(lock_path)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    token = None
    try:
        if os.fstat(fd).st_nlink != 1:
            raise MemoryConflict("memory lock has unexpected links")
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        token = _held.set((lock_path, exclusive))
        yield
    finally:
        if token is not None:
            _held.reset(token)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def pending(conn):
    return conn.execute("SELECT operation_id, status FROM page_operations "
                        f"WHERE status IN {UNFINISHED}").fetchone()


@contextlib.contextmanager
def read_snapshot(*, allow_pending=False):
    """Acquire before opening SQLite transactions; hold only over local reads."""
    with memory_lock():
        path = ledger_path()
        validate_database(path)
        if path.exists():
            with contextlib.closing(sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)) as conn:
                conn.execute("BEGIN")
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
                    from migrate import refuse_if_from_the_future
                    refuse_if_from_the_future(conn)
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='page_operations'").fetchone():
                    operation = pending(conn)
                    if operation and not allow_pending:
                        raise MemoryBlocked(f"memory operation {operation[0]} is {operation[1]}; "
                                            "run memory_operations.py recover")
                    for guard in READ_GUARDS.values():
                        guard(conn)
        yield


def coordinated(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with read_snapshot():
            return fn(*args, **kwargs)
    return wrapped
