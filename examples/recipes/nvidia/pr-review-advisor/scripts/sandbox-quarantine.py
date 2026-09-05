#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Create, inspect, validate, and clear one durable sandbox quarantine."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REASON = "review_request_in_flight"
MAX_MARKER_BYTES = 32_768
FIELDS = {
    "schema_version",
    "reason",
    "requested_session_id",
    "sandbox_name",
    "install_id",
    "repository",
    "scope_digest",
    "active_runtime_fingerprint",
    "recovery_snapshot",
}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
INSTALL_ID_RE = re.compile(r"^[0-9a-f]{16}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_RE = re.compile(r"^review-memory-[A-Za-z0-9._-]+\.tar\.gz$")


class QuarantineError(ValueError):
    """The quarantine marker or one of its expected bindings is unsafe."""


@dataclass(frozen=True)
class OpenMarker:
    """An opened marker pinned to its checked parent and inode."""

    parent_fd: int
    marker_fd: int
    info: os.stat_result
    record: dict[str, Any]

    def close(self) -> None:
        os.close(self.marker_fd)
        os.close(self.parent_fd)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_checked_identity(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_uid,
        stat.S_IMODE(left.st_mode),
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_uid,
        stat.S_IMODE(right.st_mode),
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _open_parent(path: Path) -> tuple[int, str]:
    parent = path.parent
    name = path.name
    if not name:
        raise QuarantineError("quarantine marker path has no basename")
    try:
        before = parent.lstat()
    except OSError as exc:
        raise QuarantineError(
            f"cannot inspect quarantine marker parent: {exc}"
        ) from exc
    if parent.is_symlink() or not stat.S_ISDIR(before.st_mode):
        raise QuarantineError(
            "quarantine marker parent must be a non-symlink directory"
        )
    if before.st_uid != os.geteuid():
        raise QuarantineError(
            "quarantine marker parent must be owned by the current uid"
        )
    if stat.S_IMODE(before.st_mode) & 0o077:
        raise QuarantineError(
            "quarantine marker parent must not grant group or world permissions"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(parent, flags)
    except OSError as exc:
        raise QuarantineError(f"cannot open quarantine marker parent: {exc}") from exc
    after = os.fstat(descriptor)
    if (
        not _same_inode(before, after)
        or not stat.S_ISDIR(after.st_mode)
        or after.st_uid != os.geteuid()
        or stat.S_IMODE(after.st_mode) & 0o077
    ):
        os.close(descriptor)
        raise QuarantineError("quarantine marker parent changed or became unsafe")
    return descriptor, name


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QuarantineError(f"quarantine marker repeats JSON field {key!r}")
        result[key] = value
    return result


def _validate_shape(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise QuarantineError("quarantine marker schema is invalid")
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != SCHEMA_VERSION
        or record["reason"] != REASON
    ):
        raise QuarantineError("quarantine marker schema is invalid")
    string_fields = FIELDS - {"schema_version"}
    if any(not isinstance(record[field], str) for field in string_fields):
        raise QuarantineError("quarantine marker fields must be strings")
    if not NAME_RE.fullmatch(record["requested_session_id"]):
        raise QuarantineError("quarantine marker requested_session_id is invalid")
    if not NAME_RE.fullmatch(record["sandbox_name"]):
        raise QuarantineError("quarantine marker sandbox_name is invalid")
    if not INSTALL_ID_RE.fullmatch(record["install_id"]):
        raise QuarantineError("quarantine marker install_id is invalid")
    if len(record["repository"]) > 255 or not REPOSITORY_RE.fullmatch(
        record["repository"]
    ):
        raise QuarantineError("quarantine marker repository is invalid")
    if not SHA256_RE.fullmatch(record["scope_digest"]):
        raise QuarantineError("quarantine marker scope_digest is invalid")
    if not SHA256_RE.fullmatch(record["active_runtime_fingerprint"]):
        raise QuarantineError("quarantine marker active_runtime_fingerprint is invalid")
    if (
        len(record["recovery_snapshot"]) > 255
        or not SNAPSHOT_RE.fullmatch(record["recovery_snapshot"])
        or Path(record["recovery_snapshot"]).name != record["recovery_snapshot"]
    ):
        raise QuarantineError(
            "quarantine marker recovery_snapshot must be a safe basename"
        )
    return record


def _canonical(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _read_from_descriptor(descriptor: int, info: os.stat_result) -> dict[str, Any]:
    if not stat.S_ISREG(info.st_mode):
        raise QuarantineError("quarantine marker must be a regular non-symlink file")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise QuarantineError(
            "quarantine marker must be owned by the current uid with mode 0600"
        )
    if info.st_size > MAX_MARKER_BYTES:
        raise QuarantineError(
            f"quarantine marker exceeds the {MAX_MARKER_BYTES}-byte limit"
        )
    raw_parts: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(
            descriptor,
            min(65_536, MAX_MARKER_BYTES - total + 1),
        )
        if not chunk:
            break
        raw_parts.append(chunk)
        total += len(chunk)
        if total > MAX_MARKER_BYTES:
            raise QuarantineError(
                f"quarantine marker exceeds the {MAX_MARKER_BYTES}-byte limit"
            )
    after = os.fstat(descriptor)
    identity_before = (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_after != identity_before:
        raise QuarantineError("quarantine marker changed while it was read")
    try:
        record = json.loads(
            b"".join(raw_parts).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except QuarantineError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuarantineError("quarantine marker is not valid UTF-8 JSON") from exc
    return _validate_shape(record)


def _open_marker(path: Path) -> OpenMarker:
    parent_fd, name = _open_parent(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise QuarantineError(f"cannot open quarantine marker: {exc}") from exc
        try:
            path_info = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            descriptor_info = os.fstat(descriptor)
            if not _same_inode(path_info, descriptor_info) or stat.S_ISLNK(
                path_info.st_mode
            ):
                raise QuarantineError("quarantine marker changed or is a symlink")
            record = _read_from_descriptor(descriptor, descriptor_info)
        except BaseException:
            os.close(descriptor)
            raise
    except BaseException:
        os.close(parent_fd)
        raise
    return OpenMarker(parent_fd, descriptor, descriptor_info, record)


def _record(
    *,
    requested_session_id: str,
    sandbox_name: str,
    install_id: str,
    repository: str,
    scope_digest: str,
    active_runtime_fingerprint: str,
    recovery_snapshot: str,
) -> dict[str, Any]:
    return _validate_shape(
        {
            "schema_version": SCHEMA_VERSION,
            "reason": REASON,
            "requested_session_id": requested_session_id,
            "sandbox_name": sandbox_name,
            "install_id": install_id,
            "repository": repository,
            "scope_digest": scope_digest,
            "active_runtime_fingerprint": active_runtime_fingerprint,
            "recovery_snapshot": recovery_snapshot,
        }
    )


def _expected_record(args: argparse.Namespace) -> dict[str, Any]:
    return _record(
        requested_session_id=args.requested_session_id,
        sandbox_name=args.sandbox_name,
        install_id=args.install_id,
        repository=args.repository,
        scope_digest=args.scope_digest,
        active_runtime_fingerprint=args.active_runtime_fingerprint,
        recovery_snapshot=args.recovery_snapshot,
    )


def _require_exact(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    if actual != expected:
        mismatches = sorted(
            field for field in FIELDS if actual.get(field) != expected.get(field)
        )
        raise QuarantineError(
            "quarantine marker does not match the expected " + ", ".join(mismatches)
        )


def create_marker(path: Path, record: dict[str, Any]) -> None:
    payload = _canonical(record)
    if len(payload) > MAX_MARKER_BYTES:
        raise QuarantineError(
            f"quarantine marker exceeds the {MAX_MARKER_BYTES}-byte limit"
        )
    parent_fd, name = _open_parent(path)
    descriptor = -1
    created_info: os.stat_result | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(
                name,
                flags,
                0o600,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise QuarantineError(f"cannot create quarantine marker: {exc}") from exc
        # Record the inode before any later operation can fail so the exception
        # path can remove only the marker created by this invocation.
        created_info = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)
        created_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(created_info.st_mode)
            or created_info.st_uid != os.geteuid()
            or stat.S_IMODE(created_info.st_mode) != 0o600
        ):
            raise QuarantineError("new quarantine marker ownership or mode is unsafe")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise QuarantineError("could not finish writing quarantine marker")
            view = view[written:]
        os.fsync(descriptor)
        path_info = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not _same_inode(created_info, path_info):
            raise QuarantineError("quarantine marker changed while it was created")
        os.fsync(parent_fd)
    except BaseException:
        if created_info is not None:
            try:
                current = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if _same_inode(created_info, current):
                    os.unlink(name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def validate_marker(path: Path, expected: dict[str, Any]) -> None:
    opened = _open_marker(path)
    try:
        _require_exact(opened.record, expected)
    finally:
        opened.close()


def inspect_marker(
    path: Path,
    *,
    sandbox_name: str,
    install_id: str,
    repository: str,
    scope_digest: str,
) -> dict[str, Any]:
    expected_identity = {
        "sandbox_name": sandbox_name,
        "install_id": install_id,
        "repository": repository,
        "scope_digest": scope_digest,
    }
    _validate_shape(
        {
            "schema_version": SCHEMA_VERSION,
            "reason": REASON,
            "requested_session_id": "validation",
            **expected_identity,
            "active_runtime_fingerprint": "0" * 64,
            "recovery_snapshot": "review-memory-validation.tar.gz",
        }
    )
    opened = _open_marker(path)
    try:
        for field, expected in expected_identity.items():
            if opened.record[field] != expected:
                raise QuarantineError(
                    f"quarantine marker does not match the expected {field}"
                )
        return dict(opened.record)
    finally:
        opened.close()


def clear_marker(path: Path, expected: dict[str, Any]) -> None:
    opened = _open_marker(path)
    try:
        _require_exact(opened.record, expected)
        current = os.stat(
            path.name,
            dir_fd=opened.parent_fd,
            follow_symlinks=False,
        )
        descriptor_info = os.fstat(opened.marker_fd)
        if not _same_checked_identity(
            opened.info, current
        ) or not _same_checked_identity(
            opened.info,
            descriptor_info,
        ):
            raise QuarantineError(
                "quarantine marker inode changed before it could be cleared"
            )
        os.unlink(path.name, dir_fd=opened.parent_fd)
        os.fsync(opened.parent_fd)
    except OSError as exc:
        raise QuarantineError(f"cannot clear quarantine marker: {exc}") from exc
    finally:
        opened.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in ("create", "validate", "clear"):
        child = subparsers.add_parser(command)
        child.add_argument("--marker", required=True, type=Path)
        child.add_argument("--requested-session-id", required=True)
        child.add_argument("--sandbox-name", required=True)
        child.add_argument("--install-id", required=True)
        child.add_argument("--repository", required=True)
        child.add_argument("--scope-digest", required=True)
        child.add_argument("--active-runtime-fingerprint", required=True)
        child.add_argument("--recovery-snapshot", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--marker", required=True, type=Path)
    inspect.add_argument("--sandbox-name", required=True)
    inspect.add_argument("--install-id", required=True)
    inspect.add_argument("--repository", required=True)
    inspect.add_argument("--scope-digest", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect":
            record = inspect_marker(
                args.marker,
                sandbox_name=args.sandbox_name,
                install_id=args.install_id,
                repository=args.repository,
                scope_digest=args.scope_digest,
            )
            sys.stdout.buffer.write(_canonical(record))
        else:
            expected = _expected_record(args)
            if args.command == "create":
                create_marker(args.marker, expected)
            elif args.command == "validate":
                validate_marker(args.marker, expected)
            else:
                clear_marker(args.marker, expected)
    except (OSError, QuarantineError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
