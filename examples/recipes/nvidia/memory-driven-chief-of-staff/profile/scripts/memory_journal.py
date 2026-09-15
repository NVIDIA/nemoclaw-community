# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded, replayable file operations with transactional completion effects.

Only trusted planners call prepare. Model envelopes cannot submit registry
effects, actors, ownership receipts, or SQL. Locks surround local work only.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from _db import ledger_path, write_txn
from memory_io import (MemoryBlocked, MemoryConflict, UNFINISHED, digest,
                       clean_temporary, path_key, pending, read_bytes, replace, target, validate_database)

MAX_FILES = 32
MAX_BYTES = 8 * 1024 * 1024
PAYLOAD_DAYS = 30
COMPLETION_HANDLERS = {}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def json_digest(value):
    return digest(canonical(value).encode())


@contextlib.contextmanager
def connection():
    validate_database(ledger_path())
    with contextlib.closing(sqlite3.connect(ledger_path())) as conn:
        conn.row_factory = sqlite3.Row
        yield conn


def store_id(conn):
    return conn.execute("SELECT value FROM meta WHERE key='store_instance_id'").fetchone()[0]


def register_completion(name, *, required_tables, validate, apply, read_guard=None):
    """Code registration only. The owner migration must precede use.

    validate(conn, effect, operation) is pure and runs at prepare and replay.
    apply(conn, effect, operation) runs inside the final Foundation transaction.
    It must not commit, open a connection, take a lock, or perform file I/O.
    Optional read_guard(conn) participates in coordinated reads.
    """
    import re
    from memory_io import READ_GUARDS
    if not re.fullmatch(r"[a-z][a-z0-9_.]*\.v[1-9][0-9]*", name):
        raise ValueError("completion handler must have a versioned name")
    if name in COMPLETION_HANDLERS:
        raise ValueError("completion handler already registered")
    COMPLETION_HANDLERS[name] = (tuple(required_tables), validate, apply)
    if read_guard is not None:
        READ_GUARDS[name] = read_guard


def validate_completions(conn, effects, operation):
    for effect in effects.get("completion", []):
        handler = COMPLETION_HANDLERS.get(effect.get("handler"))
        if handler is None:
            raise MemoryBlocked("completion handler unavailable; install its compatible runtime")
        tables, validate, _ = handler
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(tables) <= existing:
            raise MemoryBlocked("completion extension migration is missing")
        # A validation hook may inspect rows but cannot commit or write them.
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        conn.set_authorizer(lambda code, *args: sqlite3.SQLITE_OK if code in allowed else sqlite3.SQLITE_DENY)
        try:
            validate(conn, effect, operation)
        finally:
            conn.set_authorizer(None)


def lookup_request(request_id, request_digest):
    with connection() as conn:
        row = conn.execute("SELECT * FROM page_operations WHERE request_id=?", (request_id,)).fetchone()
        if row and row["request_digest"] != request_digest:
            raise MemoryConflict("request ID was already used with different content")
        return dict(row) if row else None


def result_for(operation):
    return {"status": operation["status"], "operation_id": operation["operation_id"],
            "page_ids": json.loads(operation["effects_json"])["effects"].get("page_ids", [])}


def prepare(*, operation_id, request_id, request_digest, instance, op_type,
            actor, files, effects, reservations=(), supersedes=None):
    """Commit every rendered byte and effect before the first filesystem change."""
    if len(files) > MAX_FILES or sum(len(b or b"") + len(a or b"") for _, b, a in files) > MAX_BYTES:
        raise MemoryConflict("operation exceeds 32 file targets or 8 MiB of replay payload")
    if len({name for name, _, _ in files}) != len(files) and not effects.get("staged_rename"):
        raise MemoryConflict("duplicate file target in operation")
    if len(set(effects.get("page_ids", []))) != len(effects.get("page_ids", [])):
        raise MemoryConflict("duplicate page scope in operation")
    virtual = {}
    for name, before, after in files:
        key = path_key(name)
        live = virtual[key] if key in virtual else read_bytes(target(name))
        if live != before:
            raise MemoryConflict("preflight file changed; rebuild the proposal")
        virtual[key] = after
    effects = json.loads(canonical(effects))
    receipts = [{"path": path, "before": digest(b), "after": digest(a)} for path, b, a in files]
    manifest = {"effects": effects, "files": receipts, "actor": actor, "type": op_type,
                "instance": instance, "reservations": list(reservations)}
    plan_hash = json_digest(manifest)
    now = stamp()
    with write_txn() as conn:
        if instance != store_id(conn):
            raise MemoryConflict("proposal belongs to a previous store instance")
        if supersedes:
            old = conn.execute("SELECT status FROM page_operations WHERE operation_id=?", (supersedes,)).fetchone()
            if not old or old[0] != "blocked_diverged":
                raise MemoryConflict("replacement requires a blocked operation")
            conn.execute("UPDATE page_operations SET status='superseded', completed_at=? WHERE operation_id=?",
                         (now, supersedes))
            scrub(conn, supersedes)
            conn.execute("UPDATE pending_resolutions SET status='superseded', payload_json='{}', resolved_at=? "
                         "WHERE operation_id=? AND status='pending'", (now, supersedes))
        if pending(conn):
            raise MemoryBlocked("another memory operation must finish first")
        operation = {"operation_id": operation_id, "request_id": request_id, "store_instance_id": instance,
                     "plan_digest": plan_hash, "actor": actor, "op_type": op_type}
        validate_completions(conn, effects, operation)
        conn.execute("INSERT INTO page_operations(operation_id,request_id,request_digest,store_instance_id,"
                     "op_type,actor,status,effects_json,plan_digest,supersedes_id,created_at) "
                     "VALUES (?,?,?,?,?,?,'prepared',?,?,?,?)",
                     (operation_id, request_id, request_digest, instance, op_type, actor,
                      canonical(manifest), plan_hash, supersedes, now))
        for page in reservations:
            conn.execute("INSERT INTO pages VALUES (?,?, 'reserved',?,?,0,?,?)",
                         (page["page_id"], page["page_type"], page["path"], page["path_key"], now, now))
            conn.execute("INSERT INTO page_paths VALUES (?,?,?,'reserved')",
                         (page["path_key"], page["path"], page["page_id"]))
        for page_id in effects.get("page_ids", []):
            conn.execute("INSERT INTO operation_pages VALUES (?,?)", (operation_id, page_id))
        for ordinal, (name, before, after) in enumerate(files):
            kind = ("index" if name == "index.md" else "log" if name == "log.md" else
                    "sidecar" if name.endswith(("/log.md", "/log.archive.md")) else "page")
            conn.execute("INSERT INTO memory_steps(operation_id,ordinal,kind,resource_key,target_path,"
                         "before_presence,before_hash,after_presence,after_hash,before_bytes,after_bytes) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (operation_id, ordinal, kind, f"{ordinal}:{name}", name,
                          "absent" if before is None else "present", digest(before),
                          "absent" if after is None else "present", digest(after), before, after))
        for ordinal, kind in enumerate(("registry", "audit"), start=len(files)):
            payload = canonical(effects if kind == "registry" else {"type": op_type, "actor": actor})
            conn.execute("INSERT INTO memory_steps(operation_id,ordinal,kind,resource_key,before_presence,"
                         "after_presence,after_hash,payload_json) VALUES (?,?,?,?,'absent','present',?,?)",
                         (operation_id, ordinal, kind, kind, digest(payload.encode()), payload))
    return operation_id


def scrub(conn, operation_id):
    conn.execute("UPDATE memory_steps SET before_bytes=NULL,after_bytes=NULL,payload_json=NULL,"
                 "payload_cleared_at=? WHERE operation_id=?", (stamp(), operation_id))
    # Manifests contain only opaque identity, paths, field hashes, and typed
    # completion data. Completion payloads are removed at terminal transition.
    row = conn.execute("SELECT effects_json FROM page_operations WHERE operation_id=?", (operation_id,)).fetchone()
    if row:
        manifest = json.loads(row[0])
        manifest["effects"]["completion"] = [{"handler": e["handler"], "digest": json_digest(e)}
                                               for e in manifest["effects"].get("completion", [])]
        conn.execute("UPDATE page_operations SET effects_json=? WHERE operation_id=?",
                     (canonical(manifest), operation_id))


def block(operation_id, resolution_type="field_diverged", ordinal=None):
    with write_txn() as conn:
        conn.execute("UPDATE page_operations SET status='blocked_diverged' WHERE operation_id=?", (operation_id,))
        if ordinal is not None:
            conn.execute("UPDATE memory_steps SET status='conflict' WHERE operation_id=? AND ordinal=?",
                         (operation_id, ordinal))
        if not conn.execute("SELECT 1 FROM pending_resolutions WHERE operation_id=? AND resolution_type=? "
                            "AND status='pending'", (operation_id, resolution_type)).fetchone():
            conn.execute("INSERT INTO pending_resolutions(resolution_id,operation_id,resolution_type,"
                         "payload_json,created_at) VALUES (?,?,?,'{}',?)",
                         (str(uuid.uuid4()), operation_id, resolution_type, stamp()))


def apply_registry(conn, operation, effects, fault=None):
    """Fixed Foundation effects; never interpolate user-supplied SQL or columns."""
    op = operation["operation_id"]
    now = stamp()
    for page in effects.get("pages", []):
        changed = conn.execute("UPDATE pages SET state=?,path=?,path_key=?,revision=revision+1,updated_at=? "
                               "WHERE page_id=? AND revision=?",
                               (page["state"], page["path"], page["path_key"], now, page["page_id"], page["expected_revision"]))
        if changed.rowcount != 1:
            raise MemoryConflict("page registry revision changed during publication")
    for path in effects.get("paths", []):
        conn.execute("INSERT INTO page_paths VALUES (?,?,?,?) ON CONFLICT(path_key) DO UPDATE SET "
                     "path=excluded.path,disposition=excluded.disposition",
                     (path["path_key"], path["path"], path["page_id"], path["disposition"]))
    for page_id in effects.get("release_reservations", []):
        conn.execute("DELETE FROM page_paths WHERE page_id=? AND disposition='reserved'", (page_id,))
    for field in effects.get("fields", []):
        conn.execute("INSERT INTO managed_fields VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(page_id,field_path) DO UPDATE SET "
                     "last_content_hash=excluded.last_content_hash,last_evidence_digest=excluded.last_evidence_digest,"
                     "initialized=excluded.initialized,awaiting_first_review=excluded.awaiting_first_review,"
                     "review_operation_id=excluded.review_operation_id,updated_at=excluded.updated_at",
                     (field["page_id"], field["field_path"], field["content_origin"],
                      field["ownership_operation_id"], field.get("review_operation_id"), field["ownership_policy"],
                      field["last_content_hash"], field.get("last_evidence_digest"), 1,
                      field["awaiting_first_review"], now))
    for review in effects.get("reviews", []):
        conn.execute("UPDATE managed_fields SET awaiting_first_review=0,review_operation_id=?,updated_at=? "
                     "WHERE page_id=? AND field_path=?", (op, now, review["page_id"], review["field_path"]))
    for resolution in effects.get("resolutions", []):
        conn.execute("INSERT INTO pending_resolutions(resolution_id,operation_id,page_id,resolution_type,"
                     "payload_json,created_at) VALUES (?,?,?,'adoption_review',?,?)",
                     (str(uuid.uuid4()), op, resolution["page_id"], canonical(resolution), now))
    for resolution in effects.get("resolved", []):
        conn.execute("UPDATE pending_resolutions SET status='resolved',choice=?,decision_digest=?,"
                     "payload_json='{}',resolved_at=? WHERE resolution_id=? AND status='pending'",
                     (resolution["choice"], resolution["digest"], now, resolution["id"]))
    for page_id in effects.get("forget", []):
        # No old operation may retain replayable text for a forgotten page.
        ids = [r[0] for r in conn.execute("SELECT operation_id FROM operation_pages WHERE page_id=?", (page_id,))]
        for old in ids:
            if old != op:
                scrub(conn, old)
        conn.execute("UPDATE pending_resolutions SET payload_json='{}',status='superseded',resolved_at=? "
                     "WHERE page_id=? AND status='pending'", (now, page_id))
        conn.execute("DELETE FROM managed_fields WHERE page_id=?", (page_id,))
    if fault:
        fault("registry", None)
    conn.execute("INSERT INTO page_events VALUES (?,?,?,?,?,?)",
                 (str(uuid.uuid4()), op, operation["actor"], operation["op_type"],
                  canonical({"page_ids": effects.get("page_ids", []), "plan_digest": operation["plan_digest"]}), now))
    if fault:
        fault("audit", None)


def recover_locked(*, fault=None):
    """Replay only frozen bytes, acknowledging after-images left by a crash."""
    with connection() as conn:
        current = pending(conn)
        if not current:
            return {"status": "clean"}
        operation = dict(conn.execute("SELECT * FROM page_operations WHERE operation_id=?", (current[0],)).fetchone())
        steps = [dict(r) for r in conn.execute("SELECT * FROM memory_steps WHERE operation_id=? ORDER BY ordinal",
                                             (current[0],))]
        if operation["status"] == "blocked_diverged":
            raise MemoryBlocked(f"memory operation {current[0]} requires reviewed resolution")
        if operation["store_instance_id"] != store_id(conn):
            raise MemoryBlocked("journal belongs to a previous store instance")
        manifest = json.loads(operation["effects_json"])
        if json_digest(manifest) != operation["plan_digest"]:
            raise MemoryBlocked("journal manifest digest mismatch")
        receipts = [{"path": s["target_path"], "before": s["before_hash"], "after": s["after_hash"]}
                    for s in steps if s["target_path"] is not None]
        if receipts != manifest["files"] or [s["ordinal"] for s in steps] != list(range(len(steps))):
            raise MemoryBlocked("journal steps disagree with the frozen manifest")
        metadata = [s for s in steps if s["target_path"] is None]
        if [s["kind"] for s in metadata] != ["registry", "audit"]:
            raise MemoryBlocked("journal metadata steps are incomplete")
        expected = [canonical(manifest["effects"]), canonical({"type": operation["op_type"], "actor": operation["actor"]})]
        if any(s["payload_json"] != text or s["after_hash"] != digest(text.encode()) for s, text in zip(metadata, expected)):
            raise MemoryBlocked("journal metadata payload mismatch")
        validate_completions(conn, manifest["effects"], operation)
    op = operation["operation_id"]
    for step in steps:
        if step["target_path"] is None:
            continue
        if step["payload_cleared_at"] is not None:
            block(op, "payload_expired")
            raise MemoryBlocked("replay bytes expired; supply a reviewed replacement")
        for side in ("before", "after"):
            if digest(step[side + "_bytes"]) != step[side + "_hash"]:
                block(op)
                raise MemoryBlocked("journal payload digest mismatch")
        if step["status"] == "applied":
            continue
        try:
            clean_temporary(step["target_path"], f"{op}-{step['ordinal']}", step["after_bytes"])
            live = read_bytes(target(step["target_path"]))
            if digest(live) != step["after_hash"]:
                if digest(live) != step["before_hash"]:
                    raise MemoryConflict("file matches neither recorded image")
                if fault:
                    fault("before_file", step["ordinal"])
                # Durable intent precedes the syscall. After a crash we cannot
                # prove that a write never happened merely because an editor
                # subsequently restored the before-image.
                with write_txn() as conn:
                    conn.execute("UPDATE page_operations SET status='applying' WHERE operation_id=?", (op,))
                replace(step["target_path"], step["before_bytes"], step["after_bytes"], token=f"{op}-{step['ordinal']}")
                if fault:
                    fault("after_file", step["ordinal"])
            with write_txn() as conn:
                conn.execute("UPDATE memory_steps SET status='applied',applied_at=? WHERE operation_id=? AND ordinal=?",
                             (stamp(), op, step["ordinal"]))
        except (MemoryConflict, FileExistsError):
            block(op, ordinal=step["ordinal"])
            raise MemoryBlocked(f"memory operation {op} diverged; live content preserved") from None
    # Check all files again, including previously acknowledged effects, before
    # committing a complete registry view. Editors ignoring the lock can race;
    # this is a protocol for cooperating writers, not a filesystem transaction.
    final_steps = {path_key(s["target_path"]): s for s in steps if s["target_path"]}
    for step in final_steps.values():
        if step["target_path"] and digest(read_bytes(target(step["target_path"]))) != step["after_hash"]:
            block(op, ordinal=step["ordinal"])
            raise MemoryBlocked("file changed before operation completion")
    with write_txn() as conn:
        apply_registry(conn, operation, manifest["effects"], fault=fault)
        for effect in manifest["effects"].get("completion", []):
            # Even an accidental callback commit must not separate extension
            # receipts from Foundation completion. The enclosing transaction
            # remains solely owned by write_txn.
            conn.set_authorizer(lambda code, *args: sqlite3.SQLITE_DENY if code in {
                sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_ATTACH,
                sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA} else sqlite3.SQLITE_OK)
            try:
                COMPLETION_HANDLERS[effect["handler"]][2](conn, effect, operation)
            finally:
                conn.set_authorizer(None)
        if fault:
            fault("completion", None)
        conn.execute("UPDATE memory_steps SET status='applied',applied_at=? WHERE operation_id=?", (stamp(), op))
        conn.execute("UPDATE page_operations SET status='complete',completed_at=? WHERE operation_id=?", (stamp(), op))
        scrub(conn, op)
    return {"status": "complete", "operation_id": op}


def expire_locked(*, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=PAYLOAD_DAYS)).isoformat(timespec="seconds")
    with connection() as conn:
        operations = [r[0] for r in conn.execute(f"SELECT operation_id FROM page_operations WHERE status IN {UNFINISHED} "
                                                "AND created_at < ?", (cutoff,))]
    for op in operations:
        with connection() as conn:
            steps = [dict(r) for r in conn.execute("SELECT * FROM memory_steps WHERE operation_id=? AND target_path IS NOT NULL", (op,))]
        for step in steps:
            clean_temporary(step["target_path"], f"{op}-{step['ordinal']}", step["after_bytes"])
        with write_txn() as conn:
            scrub(conn, op)
            conn.execute("UPDATE pending_resolutions SET payload_json='{}' WHERE operation_id=?", (op,))
        block(op, "payload_expired")
    return len(operations)
