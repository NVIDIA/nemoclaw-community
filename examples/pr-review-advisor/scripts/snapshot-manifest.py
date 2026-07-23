#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Create and validate repository-bound review-memory snapshot manifests."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tarfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 2
MANIFEST_FIELDS = {
    "schema_version",
    "sandbox",
    "install_id",
    "repository",
    "created_at",
    "archive",
    "sha256",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
ARCHIVE_NAME_RE = re.compile(r"^review-memory-[A-Za-z0-9._-]+\.tar\.gz$")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TAR_STREAM_BYTES = 192 * 1024 * 1024
MAX_NAME_BYTES = 4096
MAX_COMPONENT_BYTES = 255
MAX_PATH_DEPTH = 64


class SnapshotError(ValueError):
    """A snapshot or its manifest is unsafe or does not match this install."""


def regular_file(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SnapshotError(f"cannot inspect {label}: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SnapshotError(f"{label} must be a regular non-symlink file")
    return info


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_manifest_name(archive: Path) -> str:
    if not ARCHIVE_NAME_RE.fullmatch(archive.name):
        raise SnapshotError("snapshot archive name is invalid")
    return f"{archive.name[:-len('.tar.gz')]}.manifest.json"


def copy_regular_file(
    source: Path,
    destination: Path,
    *,
    label: str,
    maximum: int,
) -> None:
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source, source_flags)
    except OSError as exc:
        raise SnapshotError(f"cannot open {label}: {exc}") from exc
    destination_fd = -1
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode):
            raise SnapshotError(f"{label} must be a regular non-symlink file")
        if before.st_size > maximum:
            raise SnapshotError(f"{label} exceeds the {maximum}-byte limit")
        destination_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            destination_flags |= os.O_NOFOLLOW
        try:
            destination_fd = os.open(destination, destination_flags, 0o600)
        except OSError as exc:
            raise SnapshotError(f"cannot stage {label}: {exc}") from exc
        copied = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > maximum:
                raise SnapshotError(f"{label} exceeds the {maximum}-byte limit")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise SnapshotError(f"could not finish staging {label}")
                view = view[written:]
        after = os.fstat(source_fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if copied != before.st_size or identity_after != identity_before:
            raise SnapshotError(f"{label} changed while it was staged")
        os.fchmod(destination_fd, 0o600)
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)


def stage_pair(archive: Path, manifest: Path, destination: Path) -> None:
    try:
        destination_info = destination.lstat()
    except OSError as exc:
        raise SnapshotError(f"cannot inspect private staging directory: {exc}") from exc
    if destination.is_symlink() or not stat.S_ISDIR(destination_info.st_mode):
        raise SnapshotError("private staging path must be a non-symlink directory")
    manifest_name = expected_manifest_name(archive)
    if manifest.name != manifest_name:
        raise SnapshotError("snapshot manifest basename does not match archive")
    staged_archive = destination / archive.name
    staged_manifest = destination / manifest_name
    try:
        copy_regular_file(
            archive,
            staged_archive,
            label="snapshot",
            maximum=MAX_ARCHIVE_BYTES,
        )
        copy_regular_file(
            manifest,
            staged_manifest,
            label="snapshot manifest",
            maximum=MAX_MANIFEST_BYTES,
        )
    except BaseException:
        staged_archive.unlink(missing_ok=True)
        staged_manifest.unlink(missing_ok=True)
        raise


def validate_archive_members(path: Path) -> None:
    info = regular_file(path, "snapshot")
    if info.st_size > MAX_ARCHIVE_BYTES:
        raise SnapshotError(
            f"snapshot archive exceeds the {MAX_ARCHIVE_BYTES}-byte compressed limit"
        )
    try:
        expanded_bytes = 0
        with gzip.open(path, "rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                expanded_bytes += len(chunk)
                if expanded_bytes > MAX_TAR_STREAM_BYTES:
                    raise SnapshotError(
                        "snapshot tar stream exceeds the "
                        f"{MAX_TAR_STREAM_BYTES}-byte expansion limit"
                    )
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise SnapshotError(f"snapshot gzip stream is invalid: {exc}") from exc
    member_count = 0
    uncompressed_bytes = 0
    entries: dict[tuple[str, ...], tuple[str, bool]] = {}
    implied_directories: dict[tuple[str, ...], str] = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                member_count += 1
                if member_count > MAX_MEMBERS:
                    raise SnapshotError(
                        f"snapshot has more than {MAX_MEMBERS} members"
                    )
                raw_name = member.name
                if member.isdir() and raw_name.endswith("/"):
                    raw_name = raw_name[:-1]
                raw_parts = raw_name.split("/")
                if (
                    not raw_name
                    or raw_name.startswith("/")
                    or "\\" in raw_name
                    or any(part in ("", ".", "..") for part in raw_parts)
                ):
                    raise SnapshotError(f"unsafe snapshot entry: {member.name}")
                try:
                    encoded_name = raw_name.encode("utf-8", "strict")
                    encoded_parts = [
                        component.encode("utf-8", "strict") for component in raw_parts
                    ]
                except UnicodeEncodeError as exc:
                    raise SnapshotError(
                        f"snapshot entry is not valid UTF-8: {member.name!r}"
                    ) from exc
                if len(encoded_name) > MAX_NAME_BYTES:
                    raise SnapshotError(
                        f"snapshot entry name exceeds {MAX_NAME_BYTES} bytes"
                    )
                if len(raw_parts) > MAX_PATH_DEPTH:
                    raise SnapshotError(
                        f"snapshot entry exceeds {MAX_PATH_DEPTH} path components"
                    )
                if any(len(component) > MAX_COMPONENT_BYTES for component in encoded_parts):
                    raise SnapshotError(
                        f"snapshot entry component exceeds {MAX_COMPONENT_BYTES} bytes"
                    )
                if any(
                    ord(character) < 32 or ord(character) == 127
                    for character in raw_name
                ):
                    raise SnapshotError(
                        f"snapshot entry contains control characters: {member.name!r}"
                    )
                parts = PurePosixPath(raw_name).parts
                if not parts or parts[0] != "memories":
                    raise SnapshotError(f"unsafe snapshot entry: {member.name}")
                if not (member.isdir() or member.isfile()):
                    raise SnapshotError(
                        f"unsupported snapshot entry type: {member.name}"
                    )
                if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                    raise SnapshotError(
                        f"snapshot member exceeds the {MAX_MEMBER_BYTES}-byte limit: "
                        f"{member.name}"
                    )
                if member.isdir() and member.size != 0:
                    raise SnapshotError(
                        f"snapshot directory has a nonzero size: {member.name}"
                    )
                uncompressed_bytes += member.size
                if uncompressed_bytes > MAX_UNCOMPRESSED_BYTES:
                    raise SnapshotError(
                        "snapshot exceeds the "
                        f"{MAX_UNCOMPRESSED_BYTES}-byte uncompressed limit"
                    )

                normalized_parts = tuple(
                    unicodedata.normalize("NFC", component).casefold()
                    for component in parts
                )
                if any(
                    component.rstrip(" .") != component
                    for component in normalized_parts
                ):
                    raise SnapshotError(
                        f"snapshot entry has an unsafe portable path: {member.name}"
                    )
                portable_key = tuple(
                    component.rstrip(" .") for component in normalized_parts
                )
                if any(not component for component in portable_key):
                    raise SnapshotError(
                        f"snapshot entry has an unsafe portable path: {member.name}"
                    )
                prior = entries.get(portable_key)
                if prior is not None:
                    raise SnapshotError(
                        "snapshot entries collide on a portable filesystem: "
                        f"{prior[0]!r} and {member.name!r}"
                    )
                if not member.isdir() and portable_key in implied_directories:
                    raise SnapshotError(
                        "snapshot entries have a file/directory collision: "
                        f"{member.name!r} and "
                        f"{implied_directories[portable_key]!r}"
                    )
                for length in range(1, len(portable_key)):
                    prefix = portable_key[:length]
                    ancestor = entries.get(prefix)
                    if ancestor is not None and not ancestor[1]:
                        raise SnapshotError(
                            "snapshot entries have a file/directory collision: "
                            f"{ancestor[0]!r} and {member.name!r}"
                        )
                    implied_directories.setdefault(prefix, member.name)
                entries[portable_key] = (member.name, member.isdir())
    except (OSError, tarfile.TarError) as exc:
        raise SnapshotError(f"snapshot archive is invalid: {exc}") from exc
    if member_count == 0:
        raise SnapshotError("snapshot is empty")


def manifest_object(
    *,
    archive: Path,
    sandbox: str,
    install_id: str,
    repository: str,
    created_at: str,
) -> dict[str, Any]:
    if not all((sandbox, install_id, repository)):
        raise SnapshotError("snapshot identity fields must be non-empty")
    if not CREATED_AT_RE.fullmatch(created_at):
        raise SnapshotError("snapshot created_at is invalid")
    expected_manifest_name(archive)
    regular_file(archive, "snapshot")
    validate_archive_members(archive)
    return {
        "schema_version": SCHEMA_VERSION,
        "sandbox": sandbox,
        "install_id": install_id,
        "repository": repository,
        "created_at": created_at,
        "archive": archive.name,
        "sha256": sha256_file(archive),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    payload = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SnapshotError(f"cannot create snapshot manifest: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def read_manifest(path: Path) -> dict[str, Any]:
    regular_file(path, "snapshot manifest")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot manifest: {exc}") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise SnapshotError("snapshot manifest is too large")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SnapshotError(
                    f"snapshot manifest repeats JSON field {key!r}"
                )
            result[key] = value
        return result

    try:
        manifest = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("snapshot manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise SnapshotError("snapshot manifest schema is invalid")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError("snapshot manifest schema is invalid")
    return manifest


def validate_manifest(
    *,
    archive: Path,
    manifest_path: Path,
    sandbox: str,
    install_id: str,
    repository: str,
) -> None:
    if manifest_path.name != expected_manifest_name(archive):
        raise SnapshotError("snapshot manifest basename does not match archive")
    regular_file(archive, "snapshot")
    manifest = read_manifest(manifest_path)
    expected_identity = {
        "sandbox": sandbox,
        "install_id": install_id,
        "repository": repository,
    }
    for field, expected in expected_identity.items():
        actual = manifest.get(field)
        if actual != expected:
            raise SnapshotError(
                f"snapshot belongs to a different {field}: "
                f"{actual!r}, expected {expected!r}"
            )
    if not isinstance(manifest.get("created_at"), str) or not CREATED_AT_RE.fullmatch(
        manifest["created_at"]
    ):
        raise SnapshotError("snapshot manifest created_at is invalid")
    if manifest.get("archive") != archive.name:
        raise SnapshotError("snapshot manifest archive name does not match")
    expected_digest = manifest.get("sha256")
    if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
        raise SnapshotError("snapshot manifest digest is invalid")
    if not hmac.compare_digest(sha256_file(archive), expected_digest):
        raise SnapshotError("snapshot archive digest does not match its manifest")
    validate_archive_members(archive)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in ("create", "validate"):
        child = subparsers.add_parser(command)
        child.add_argument("--archive", required=True, type=Path)
        child.add_argument("--manifest", required=True, type=Path)
        child.add_argument("--sandbox", required=True)
        child.add_argument("--install-id", required=True)
        child.add_argument("--repository", required=True)
        if command == "create":
            child.add_argument("--created-at", required=True)
    stage = subparsers.add_parser("stage")
    stage.add_argument("--archive", required=True, type=Path)
    stage.add_argument("--manifest", required=True, type=Path)
    stage.add_argument("--destination", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "stage":
            stage_pair(args.archive, args.manifest, args.destination)
        elif args.command == "create":
            if args.manifest.name != expected_manifest_name(args.archive):
                raise SnapshotError(
                    "snapshot manifest basename does not match archive"
                )
            manifest = manifest_object(
                archive=args.archive,
                sandbox=args.sandbox,
                install_id=args.install_id,
                repository=args.repository,
                created_at=args.created_at,
            )
            write_manifest(args.manifest, manifest)
        else:
            validate_manifest(
                archive=args.archive,
                manifest_path=args.manifest,
                sandbox=args.sandbox,
                install_id=args.install_id,
                repository=args.repository,
            )
    except SnapshotError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
