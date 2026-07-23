# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Repository-bound review-memory snapshot manifest tests."""

from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "snapshot-manifest.py"
SNAPSHOT_SCRIPT = SCRIPT.with_name("snapshot.sh")
RESTORE_SCRIPT = SCRIPT.with_name("restore.sh")
SANDBOX = "pr-review-0123456789abcdef"
INSTALL_ID = "0123456789abcdef"
REPOSITORY = "example/project"
CREATED_AT = "2026-07-23T12-34-56Z"


def run_manifest(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def write_snapshot(path: Path, *, unsafe_link: bool = False) -> None:
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("memories")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o700
        archive.addfile(directory)
        if unsafe_link:
            link = tarfile.TarInfo("memories/escape")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../escape"
            archive.addfile(link)
        else:
            payload = b"maintainer-authored lesson\n"
            lesson = tarfile.TarInfo("memories/lesson.md")
            lesson.size = len(payload)
            lesson.mode = 0o600
            archive.addfile(lesson, io.BytesIO(payload))


class ZeroReader(io.RawIOBase):
    def __init__(self, size: int) -> None:
        self.remaining = size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.remaining == 0:
            return b""
        count = self.remaining if size < 0 else min(size, self.remaining)
        self.remaining -= count
        return b"\0" * count


def write_sized_snapshot(path: Path, sizes: list[int]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("memories")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for index, size in enumerate(sizes):
            member = tarfile.TarInfo(f"memories/lesson-{index}.bin")
            member.size = size
            archive.addfile(member, ZeroReader(size))


def create_args(archive: Path, manifest: Path) -> list[str]:
    return [
        "create",
        "--archive",
        str(archive),
        "--manifest",
        str(manifest),
        "--sandbox",
        SANDBOX,
        "--install-id",
        INSTALL_ID,
        "--repository",
        REPOSITORY,
        "--created-at",
        CREATED_AT,
    ]


def validate_args(archive: Path, manifest: Path) -> list[str]:
    return [
        "validate",
        "--archive",
        str(archive),
        "--manifest",
        str(manifest),
        "--sandbox",
        SANDBOX,
        "--install-id",
        INSTALL_ID,
        "--repository",
        REPOSITORY,
    ]


def test_snapshot_manifest_v2_binds_install_repository_and_sandbox(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "review-memory-test.tar.gz"
    manifest = tmp_path / "review-memory-test.manifest.json"
    write_snapshot(archive)

    created = run_manifest(*create_args(archive, manifest))
    assert created.returncode == 0, created.stderr
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value == {
        "schema_version": 2,
        "sandbox": SANDBOX,
        "install_id": INSTALL_ID,
        "repository": REPOSITORY,
        "created_at": CREATED_AT,
        "archive": archive.name,
        "sha256": value["sha256"],
    }
    assert manifest.stat().st_mode & 0o777 == 0o600

    validated = run_manifest(*validate_args(archive, manifest))
    assert validated.returncode == 0, validated.stderr

    stage = tmp_path / "private-stage"
    stage.mkdir(mode=0o700)
    staged = run_manifest(
        "stage",
        "--archive",
        str(archive),
        "--manifest",
        str(manifest),
        "--destination",
        str(stage),
    )
    assert staged.returncode == 0, staged.stderr
    archive.write_bytes(b"changed after staging")
    manifest.write_text("{}\n", encoding="utf-8")
    staged_validation = run_manifest(
        *validate_args(stage / archive.name, stage / manifest.name)
    )
    assert staged_validation.returncode == 0, staged_validation.stderr

    original = value.copy()
    for field, replacement in (
        ("sandbox", "pr-review-fedcba9876543210"),
        ("install_id", "fedcba9876543210"),
        ("repository", "other/project"),
    ):
        changed = original | {field: replacement}
        staged_manifest = stage / manifest.name
        staged_manifest.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        rejected = run_manifest(
            *validate_args(stage / archive.name, staged_manifest)
        )
        assert rejected.returncode == 1
        assert f"different {field}" in rejected.stderr


def test_snapshot_manifest_rejects_digest_drift_and_unsafe_members(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "review-memory-test.tar.gz"
    manifest = tmp_path / "review-memory-test.manifest.json"
    write_snapshot(archive)
    assert run_manifest(*create_args(archive, manifest)).returncode == 0

    with archive.open("ab") as stream:
        stream.write(b"tampered")
    rejected = run_manifest(*validate_args(archive, manifest))
    assert rejected.returncode == 1
    assert "digest does not match" in rejected.stderr

    unsafe_archive = tmp_path / "review-memory-unsafe.tar.gz"
    unsafe_manifest = tmp_path / "review-memory-unsafe.manifest.json"
    write_snapshot(unsafe_archive, unsafe_link=True)
    unsafe = run_manifest(*create_args(unsafe_archive, unsafe_manifest))
    assert unsafe.returncode == 1
    assert "unsupported snapshot entry type" in unsafe.stderr
    assert not unsafe_manifest.exists()


def test_snapshot_rejects_resource_bombs_and_portable_collisions(
    tmp_path: Path,
) -> None:
    oversized_archive = tmp_path / "review-memory-oversized.tar.gz"
    oversized_manifest = tmp_path / "review-memory-oversized.manifest.json"
    write_sized_snapshot(oversized_archive, [16 * 1024 * 1024 + 1])
    oversized = run_manifest(
        *create_args(oversized_archive, oversized_manifest)
    )
    assert oversized.returncode == 1
    assert "snapshot member exceeds" in oversized.stderr

    cumulative_archive = tmp_path / "review-memory-cumulative.tar.gz"
    cumulative_manifest = tmp_path / "review-memory-cumulative.manifest.json"
    write_sized_snapshot(
        cumulative_archive,
        [16 * 1024 * 1024] * 8 + [1],
    )
    cumulative = run_manifest(
        *create_args(cumulative_archive, cumulative_manifest)
    )
    assert cumulative.returncode == 1
    assert "uncompressed limit" in cumulative.stderr

    too_many_archive = tmp_path / "review-memory-members.tar.gz"
    too_many_manifest = tmp_path / "review-memory-members.manifest.json"
    with tarfile.open(too_many_archive, "w:gz") as archive:
        directory = tarfile.TarInfo("memories")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for index in range(10_000):
            archive.addfile(tarfile.TarInfo(f"memories/{index}"))
    too_many = run_manifest(*create_args(too_many_archive, too_many_manifest))
    assert too_many.returncode == 1
    assert "more than 10000 members" in too_many.stderr

    collision_archive = tmp_path / "review-memory-collision.tar.gz"
    collision_manifest = tmp_path / "review-memory-collision.manifest.json"
    with tarfile.open(collision_archive, "w:gz") as archive:
        directory = tarfile.TarInfo("memories")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        archive.addfile(tarfile.TarInfo("memories/Lesson.md"))
        archive.addfile(tarfile.TarInfo("memories/lesson.md"))
    collision = run_manifest(
        *create_args(collision_archive, collision_manifest)
    )
    assert collision.returncode == 1
    assert "collide on a portable filesystem" in collision.stderr

    deep_archive = tmp_path / "review-memory-deep.tar.gz"
    deep_manifest = tmp_path / "review-memory-deep.manifest.json"
    with tarfile.open(deep_archive, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("/".join(["memories"] + ["a"] * 64)))
    deep = run_manifest(*create_args(deep_archive, deep_manifest))
    assert deep.returncode == 1
    assert "path components" in deep.stderr

    odd_archive = tmp_path / "review-memory-odd.tar.gz"
    odd_manifest = tmp_path / "review-memory-odd.manifest.json"
    with tarfile.open(odd_archive, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("memories/./lesson"))
    odd = run_manifest(*create_args(odd_archive, odd_manifest))
    assert odd.returncode == 1
    assert "unsafe snapshot entry" in odd.stderr

    compressed_archive = tmp_path / "review-memory-compressed.tar.gz"
    compressed_manifest = tmp_path / "review-memory-compressed.manifest.json"
    with compressed_archive.open("wb") as stream:
        stream.seek(64 * 1024 * 1024)
        stream.write(b"x")
    compressed = run_manifest(
        *create_args(compressed_archive, compressed_manifest)
    )
    assert compressed.returncode == 1
    assert "compressed limit" in compressed.stderr

    expansion_archive = tmp_path / "review-memory-expansion.tar.gz"
    expansion_manifest = tmp_path / "review-memory-expansion.manifest.json"
    zero_chunk = b"\0" * (1024 * 1024)
    with gzip.open(expansion_archive, "wb") as stream:
        for _ in range(193):
            stream.write(zero_chunk)
    expansion = run_manifest(
        *create_args(expansion_archive, expansion_manifest)
    )
    assert expansion.returncode == 1
    assert "expansion limit" in expansion.stderr


def test_snapshot_lifecycle_passes_all_binding_fields_and_retains_rollback() -> None:
    snapshot_source = SNAPSHOT_SCRIPT.read_text(encoding="utf-8")
    restore_source = RESTORE_SCRIPT.read_text(encoding="utf-8")
    for source in (snapshot_source, restore_source):
        assert '"$DIR/snapshot-manifest.py"' in source
        assert '--sandbox "$NEMOCLAW_SANDBOX_NAME"' in source
        assert '--install-id "$REVIEW_ADVISOR_INSTALL_ID"' in source
        assert '--repository "$REVIEW_ADVISOR_REPOSITORY"' in source
    assert "remote_stage=" in restore_source
    assert '"$DIR/snapshot-manifest.py" stage' in restore_source
    assert '"$staged_archive" "$remote"' in restore_source
    assert 'tar -czf "$backup" -C "$home" memories' in restore_source
    assert 'tar -xzf "$backup" -C "$home"' in restore_source
    assert "previous memory was restored" in restore_source
