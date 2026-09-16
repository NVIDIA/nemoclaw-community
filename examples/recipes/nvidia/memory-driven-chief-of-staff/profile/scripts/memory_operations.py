# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Foundation status, coherent reads, activation, and deterministic maintenance."""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3

from _db import ledger_path, write_txn
from memory_io import (MemoryBlocked, MemoryConflict, digest, memory_lock,
                       path_key, pending, read_bytes, read_snapshot, target, validate_database)
import memory_journal as journal
from memory_pages import compatibility, writer


def check():
    """Observational: do not initialize, migrate, recover, or expire the store."""
    path = ledger_path()
    validate_database(path)
    if not path.exists():
        return {"status": "uninitialized", "enabled": False}
    with contextlib.closing(sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='memory_control'").fetchone():
            return {"status": "migration_required", "enabled": False}
        operation = pending(conn)
        return {"status": operation[1] if operation else "clean",
                "operation_id": operation[0] if operation else None,
                "store_instance_id": journal.store_id(conn),
                "enabled": bool(conn.execute("SELECT enabled FROM memory_control").fetchone()[0]),
                "resolutions": [dict(r) for r in conn.execute("SELECT resolution_id,operation_id,page_id,"
                    "resolution_type FROM pending_resolutions WHERE status='pending'")]}


def recover():
    with writer(check_skills=False, recover=False):
        return journal.recover_locked()


def set_enabled(value):
    with writer(check_skills=value, recover=value, expire=value):
        with write_txn() as conn:
            conn.execute("UPDATE memory_control SET enabled=? WHERE singleton=1", (int(value),))
    return {"enabled": value}


def snapshot(paths):
    with read_snapshot():
        status = check()
        result = {"store_instance_id": status.get("store_instance_id"), "files": {}, "pages": []}
        with journal.connection() as conn:
            result["pages"] = [dict(row) for row in conn.execute("SELECT page_id,path,state,revision FROM pages WHERE state!='deleted'")]
            for name in paths:
                route = conn.execute("SELECT p.page_id,p.path,p.state FROM page_paths a JOIN pages p USING(page_id) "
                                     "WHERE a.path_key=?", (path_key(name),)).fetchone()
                canonical = route["path"] if route else name
                data = None if route and route["state"] == "deleted" else read_bytes(target(canonical))
                result["files"][name] = {"expected_hash": digest(data), "text": None if data is None else data.decode(),
                                         "canonical_path": canonical, "page_id": route["page_id"] if route else None,
                                         "state": route["state"] if route else "unmanaged"}
        return result


def inspect_operation():
    """Review actual partial files explicitly without presenting current memory."""
    with memory_lock():
        status = check()
        operation_id = status.get("operation_id")
        result = {**status, "current_memory": False, "observed": {}, "files": {}}
        if operation_id is None:
            return result
        with journal.connection() as conn:
            paths = [r[0] for r in conn.execute("SELECT DISTINCT target_path FROM memory_steps "
                                               "WHERE operation_id=? AND target_path IS NOT NULL", (operation_id,))]
        for name in paths:
            data = read_bytes(target(name))
            result["observed"][name] = digest(data)
            result["files"][name] = data.decode() if data is not None else None
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "inspect", "recover", "enable", "disable", "read", "maintain", "gate"))
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command == "check":
            result = check()
        elif args.command == "inspect":
            result = inspect_operation()
        elif args.command == "read":
            result = snapshot(args.paths or ["index.md"])
        elif args.command in {"enable", "disable"}:
            result = set_enabled(args.command == "enable")
        else:
            with writer(check_skills=args.command == "gate", recover=False):
                result = journal.recover_locked()
            if args.command == "gate":
                result = check()
    except (MemoryBlocked, MemoryConflict, ValueError) as exc:
        result = {"status": "blocked", "detail": str(exc)}
        code = 3
    print(json.dumps(result))
    if args.command == "maintain" or code:
        print(json.dumps({"wakeAgent": False}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
