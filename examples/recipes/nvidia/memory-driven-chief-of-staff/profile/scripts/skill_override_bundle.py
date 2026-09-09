# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Versioned recovery snapshots for skill overrides, without executable SQL.

The bundle contains every override, retained base, distribution approval,
observation, applied manifest and operation record. Live skill bytes are
included as recovery evidence; importing never overwrites installed skills.
Only restore bundles from a trusted export: hashes detect corruption, not
authorship. Validation builds a fresh database from this module's schema,
never opens a database or executes SQL supplied by an import.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path

import skill_overrides as so

VERSION = 1
TABLES = {
    "base_blobs": ("content_hash", "first_observed_at"),
    "base_observations": ("observation_id", "skill_name", "content_hash", "observed_at"),
    "approved_bases": ("skill_name", "content_hash"),
    "distribution_bases": ("skill_name", "content_hash"),
    "applied_overrides": ("skill_name", "applied_hash", "updated_at"),
    "override_operations": ("id", "skill_name", "op_type", "status",
                            "expected_before_hash", "expected_after_hash", "created_at"),
}
HASH = re.compile(r"[0-9a-f]{64}\Z")


class InvalidBundle(ValueError):
    """A recovery snapshot cannot be restored completely."""


def _pack(data: bytes) -> dict[str, str]:
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "base64": base64.b64encode(data).decode("ascii")}


def _unpack(record: object) -> bytes:
    if not isinstance(record, dict) or set(record) != {"sha256", "base64"}:
        raise InvalidBundle("invalid file record")
    try:
        data = base64.b64decode(record["base64"], validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise InvalidBundle("invalid file encoding") from exc
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise InvalidBundle("file checksum mismatch")
    return data


def _file_parts(relative: str) -> tuple[str, str, str]:
    parts = relative.split("/")
    if len(parts) != 3 or parts[2] != "SKILL.md":
        raise InvalidBundle("unexpected recovery file path")
    kind, name, _ = parts
    if kind == "overrides":
        so._validate_skill_name(name)
    elif kind != "bases" or not HASH.fullmatch(name):
        raise InvalidBundle("unexpected recovery file path")
    return tuple(parts)


def _capture_locked(root: Path) -> dict:
    tables = {table: [] for table in TABLES}
    db = so._db_path(root)
    if so._regular_file_exists(db):
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            unknown = present - set(TABLES) - {"sqlite_sequence"}
            if unknown:
                raise InvalidBundle("unsupported tables in override database")
            for table, columns in TABLES.items():
                # Legacy snapshots preserve their history but receive no
                # retroactive approvals for automatically observed bases.
                if table in present:
                    actual = tuple(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))
                    if actual != columns:
                        raise InvalidBundle(f"unsupported {table} schema")
                    tables[table] = [dict(row) for row in conn.execute(
                        f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid")]
        finally:
            conn.close()

    files = {}
    for kind in ("bases", "overrides"):
        parent = so._safe_child(so._state_dir(root), kind)
        if not so._is_dir_strict(parent):
            continue
        for entry in sorted(parent.iterdir()):
            if entry.name.startswith("."):
                continue
            relative = f"{kind}/{entry.name}/SKILL.md"
            parts = _file_parts(relative)
            path = so._safe_child(so._state_dir(root), *parts)
            if so._regular_file_exists(path):
                files[relative] = _pack(path.read_bytes())
            elif list(so._safe_child(parent, entry.name).iterdir()):
                raise InvalidBundle("unexpected files in override state")
    live = {}
    names = {row["skill_name"] for rows in tables.values() for row in rows
             if "skill_name" in row}
    names.update(_file_parts(path)[1] for path in files if path.startswith("overrides/"))
    for name in sorted(names):
        path = so._safe_child(so._skills_dir(root), name, "SKILL.md")
        live[name] = _pack(path.read_bytes()) if so._regular_file_exists(path) else None
    result = {"format": "skill-overrides", "version": VERSION,
              "tables": tables, "files": files, "live": live}
    # A missing retained blob makes recovery incomplete. Refuse the entire
    # export instead of leaving the operator with a plausible partial copy.
    _validate(result)
    return result


def capture(root: Path) -> tuple[list, dict]:
    """Hold one barrier across the status, files and database snapshot."""
    with so._global_lock(root, exclusive=True):
        reports = so.snapshot_for_export(root, locked=True)
        return reports, _capture_locked(root)


def _validate(bundle: object) -> dict[str, bytes]:
    if not isinstance(bundle, dict) or set(bundle) != {"format", "version", "tables", "files", "live"}:
        raise InvalidBundle("invalid recovery bundle fields")
    if bundle["format"] != "skill-overrides" or type(bundle["version"]) is not int or bundle["version"] != VERSION:
        raise InvalidBundle("unsupported recovery bundle version")
    tables = bundle["tables"]
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise InvalidBundle("incomplete recovery tables")
    if not isinstance(bundle["files"], dict) or not isinstance(bundle["live"], dict):
        raise InvalidBundle("invalid recovery files")
    decoded = {}
    for relative, record in bundle["files"].items():
        parts = _file_parts(relative)
        data = _unpack(record)
        if parts[0] == "bases" and hashlib.sha256(data).hexdigest() != parts[1]:
            raise InvalidBundle("retained base does not match its name")
        decoded[relative] = data
    for name, record in bundle["live"].items():
        so._validate_skill_name(name)
        if record is not None:
            _unpack(record)
    for table, columns in TABLES.items():
        if not isinstance(tables[table], list):
            raise InvalidBundle("invalid recovery rows")
        for row in tables[table]:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise InvalidBundle(f"invalid {table} row")
            for key, value in row.items():
                if key in ("id", "observation_id"):
                    if type(value) is not int or value < 1:
                        raise InvalidBundle("invalid history identifier")
                elif not isinstance(value, str):
                    raise InvalidBundle("invalid recovery value")
                if key == "skill_name":
                    so._validate_skill_name(value)
                if key.endswith("hash") and not HASH.fullmatch(value):
                    if key != "expected_before_hash" or value != "":
                        raise InvalidBundle("invalid content hash")
    blobs = {r["content_hash"] for r in tables["base_blobs"]}
    for digest in blobs:
        if f"bases/{digest}/SKILL.md" not in decoded:
            raise InvalidBundle("recovery bundle is missing a retained base")
    approvals = {(r["skill_name"], r["content_hash"]) for r in tables["approved_bases"]}
    for row in tables["distribution_bases"]:
        if (row["skill_name"], row["content_hash"]) not in approvals:
            raise InvalidBundle("distribution base has no approval")
    # Fresh schema validates foreign keys, duplicates, operation enums and
    # single-pending-operation constraints before anything is installed.
    conn = sqlite3.connect(":memory:")
    try:
        _populate(conn, tables)
    except sqlite3.Error as exc:
        raise InvalidBundle(f"inconsistent recovery database: {exc}") from exc
    finally:
        conn.close()
    return decoded


def _populate(conn: sqlite3.Connection, tables: dict) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(so.SCHEMA)
    with conn:
        for table, columns in TABLES.items():
            marks = ", ".join("?" for _ in columns)
            conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})",
                             [tuple(row[c] for c in columns) for row in tables[table]])
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise InvalidBundle("recovery foreign-key check failed")


def _json_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidBundle("duplicate JSON field")
        result[key] = value
    return result


def restore_bundle(root: Path, path: Path) -> None:
    """Validate, stage and atomically install feature state into an empty home.

    Live skill files, the main recipe ledger, memory and credentials are not
    restored by this command. Existing feature state is never replaced.
    """
    bundle = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_object)
    files = _validate(bundle)
    with so._global_lock(root, exclusive=True):
        destination = so._state_dir(root)
        if destination.exists():
            raise InvalidBundle("override state already exists; export and reset it before restoring")
        staging = so._safe_child(root, "workspace", ".skill-overrides-restore")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            for relative, data in files.items():
                target = so._safe_child(staging, *_file_parts(relative))
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            conn = sqlite3.connect(staging / "state.db")
            try:
                _populate(conn, bundle["tables"])
            finally:
                conn.close()
            os.chmod(staging / "state.db", 0o600)
            with (staging / "state.db").open("rb") as stream:
                os.fsync(stream.fileno())
            for parent, directories, _ in os.walk(staging, topdown=False):
                os.chmod(parent, 0o700)
                so._fsync_dir(Path(parent))
            os.replace(staging, destination)
            so._fsync_dir(destination.parent)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise
