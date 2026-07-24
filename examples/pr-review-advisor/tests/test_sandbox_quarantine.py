# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Durable sandbox-quarantine marker tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "sandbox-quarantine.py"
SESSION_ID = "review-0123456789ab-abcdef012345"
SANDBOX_NAME = "pr-review-0123456789abcdef"
INSTALL_ID = "0123456789abcdef"
REPOSITORY = "example/project"
SCOPE_DIGEST = "1" * 64
RUNTIME_FINGERPRINT = "2" * 64
RECOVERY_SNAPSHOT = "review-memory-2026-07-24T01-02-03Z-abcdef12.tar.gz"


def run_quarantine(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def private_state(tmp_path: Path, name: str = "state") -> Path:
    state = tmp_path / name
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    return state


def full_args(command: str, marker: Path, **overrides: str) -> list[str]:
    values = {
        "requested_session_id": SESSION_ID,
        "sandbox_name": SANDBOX_NAME,
        "install_id": INSTALL_ID,
        "repository": REPOSITORY,
        "scope_digest": SCOPE_DIGEST,
        "active_runtime_fingerprint": RUNTIME_FINGERPRINT,
        "recovery_snapshot": RECOVERY_SNAPSHOT,
    }
    values.update(overrides)
    return [
        command,
        "--marker",
        str(marker),
        "--requested-session-id",
        values["requested_session_id"],
        "--sandbox-name",
        values["sandbox_name"],
        "--install-id",
        values["install_id"],
        "--repository",
        values["repository"],
        "--scope-digest",
        values["scope_digest"],
        "--active-runtime-fingerprint",
        values["active_runtime_fingerprint"],
        "--recovery-snapshot",
        values["recovery_snapshot"],
    ]


def inspect_args(marker: Path, **overrides: str) -> list[str]:
    values = {
        "sandbox_name": SANDBOX_NAME,
        "install_id": INSTALL_ID,
        "repository": REPOSITORY,
        "scope_digest": SCOPE_DIGEST,
    }
    values.update(overrides)
    return [
        "inspect",
        "--marker",
        str(marker),
        "--sandbox-name",
        values["sandbox_name"],
        "--install-id",
        values["install_id"],
        "--repository",
        values["repository"],
        "--scope-digest",
        values["scope_digest"],
    ]


def expected_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "reason": "review_request_in_flight",
        "requested_session_id": SESSION_ID,
        "sandbox_name": SANDBOX_NAME,
        "install_id": INSTALL_ID,
        "repository": REPOSITORY,
        "scope_digest": SCOPE_DIGEST,
        "active_runtime_fingerprint": RUNTIME_FINGERPRINT,
        "recovery_snapshot": RECOVERY_SNAPSHOT,
    }


def write_marker(marker: Path, value: object | bytes) -> None:
    raw = (
        value
        if isinstance(value, bytes)
        else (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    )
    marker.write_bytes(raw)
    marker.chmod(0o600)


def test_quarantine_round_trip_and_canonical_inspect(tmp_path: Path) -> None:
    marker = private_state(tmp_path) / "sandbox-quarantine.json"

    created = run_quarantine(*full_args("create", marker))
    assert created.returncode == 0, created.stderr
    assert marker.stat().st_mode & 0o777 == 0o600
    assert json.loads(marker.read_text(encoding="utf-8")) == expected_record()

    validated = run_quarantine(*full_args("validate", marker))
    assert validated.returncode == 0, validated.stderr

    inspected = run_quarantine(*inspect_args(marker))
    assert inspected.returncode == 0, inspected.stderr
    canonical = (
        json.dumps(
            expected_record(),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    assert inspected.stdout == canonical

    cleared = run_quarantine(*full_args("clear", marker))
    assert cleared.returncode == 0, cleared.stderr
    assert not marker.exists()


@pytest.mark.parametrize("preexisting", ("file", "symlink"))
def test_create_never_overwrites_a_preexisting_path(
    tmp_path: Path,
    preexisting: str,
) -> None:
    state = private_state(tmp_path)
    marker = state / "sandbox-quarantine.json"
    target = state / "target"
    if preexisting == "file":
        marker.write_text("operator-owned\n", encoding="utf-8")
        marker.chmod(0o600)
    else:
        target.write_text("operator-owned\n", encoding="utf-8")
        target.chmod(0o600)
        marker.symlink_to(target)

    created = run_quarantine(*full_args("create", marker))

    assert created.returncode == 1
    if preexisting == "file":
        assert marker.read_text(encoding="utf-8") == "operator-owned\n"
    else:
        assert marker.is_symlink()
        assert target.read_text(encoding="utf-8") == "operator-owned\n"


def test_marker_mode_and_symlink_are_rejected_without_clear(
    tmp_path: Path,
) -> None:
    state = private_state(tmp_path)
    marker = state / "sandbox-quarantine.json"
    write_marker(marker, expected_record())
    marker.chmod(0o640)

    for command in ("validate", "clear"):
        result = run_quarantine(*full_args(command, marker))
        assert result.returncode == 1
        assert "mode 0600" in result.stderr
        assert marker.exists()

    marker.unlink()
    target = state / "target.json"
    write_marker(target, expected_record())
    marker.symlink_to(target)
    inspected = run_quarantine(*inspect_args(marker))
    assert inspected.returncode == 1
    assert marker.is_symlink()
    assert target.exists()


def test_non_regular_marker_is_rejected(tmp_path: Path) -> None:
    marker = private_state(tmp_path) / "sandbox-quarantine.json"
    marker.mkdir(mode=0o700)

    inspected = run_quarantine(*inspect_args(marker))

    assert inspected.returncode == 1
    assert "regular non-symlink file" in inspected.stderr
    assert marker.is_dir()


def test_unsafe_parent_permissions_and_symlink_are_rejected(
    tmp_path: Path,
) -> None:
    state = private_state(tmp_path)
    marker = state / "sandbox-quarantine.json"
    state.chmod(0o750)
    unsafe_mode = run_quarantine(*full_args("create", marker))
    assert unsafe_mode.returncode == 1
    assert "group or world permissions" in unsafe_mode.stderr
    assert not marker.exists()

    state.chmod(0o700)
    real_state = private_state(tmp_path, "real-state")
    linked_state = tmp_path / "linked-state"
    linked_state.symlink_to(real_state, target_is_directory=True)
    linked_marker = linked_state / "sandbox-quarantine.json"
    unsafe_link = run_quarantine(*full_args("create", linked_marker))
    assert unsafe_link.returncode == 1
    assert "non-symlink directory" in unsafe_link.stderr
    assert not (real_state / "sandbox-quarantine.json").exists()


@pytest.mark.parametrize(
    ("field", "wrong"),
    (
        ("requested_session_id", "wrong-session"),
        ("sandbox_name", "other-sandbox"),
        ("install_id", "fedcba9876543210"),
        ("repository", "other/project"),
        ("scope_digest", "3" * 64),
        ("active_runtime_fingerprint", "4" * 64),
        ("recovery_snapshot", "review-memory-other.tar.gz"),
    ),
)
def test_validate_and_clear_require_every_exact_field(
    tmp_path: Path,
    field: str,
    wrong: str,
) -> None:
    marker = private_state(tmp_path) / "sandbox-quarantine.json"
    created = run_quarantine(*full_args("create", marker))
    assert created.returncode == 0, created.stderr

    validation = run_quarantine(*full_args("validate", marker, **{field: wrong}))
    assert validation.returncode == 1
    assert field in validation.stderr

    cleared = run_quarantine(*full_args("clear", marker, **{field: wrong}))
    assert cleared.returncode == 1
    assert marker.exists()


@pytest.mark.parametrize(
    "identity",
    ("sandbox_name", "install_id", "repository", "scope_digest"),
)
def test_inspect_requires_expected_install_identity(
    tmp_path: Path,
    identity: str,
) -> None:
    marker = private_state(tmp_path) / "sandbox-quarantine.json"
    created = run_quarantine(*full_args("create", marker))
    assert created.returncode == 0, created.stderr
    wrong = {
        "sandbox_name": "other-sandbox",
        "install_id": "fedcba9876543210",
        "repository": "other/project",
        "scope_digest": "3" * 64,
    }[identity]

    inspected = run_quarantine(*inspect_args(marker, **{identity: wrong}))

    assert inspected.returncode == 1
    assert identity in inspected.stderr


@pytest.mark.parametrize(
    "mutator",
    (
        lambda record: {**record, "schema_version": 2},
        lambda record: {**record, "reason": "stream_not_joined"},
        lambda record: {**record, "requested_session_id": "../escape"},
        lambda record: {**record, "sandbox_name": "bad/name"},
        lambda record: {**record, "install_id": "A" * 16},
        lambda record: {**record, "repository": "missing-slash"},
        lambda record: {**record, "scope_digest": "A" * 64},
        lambda record: {
            **record,
            "active_runtime_fingerprint": "short",
        },
        lambda record: {
            **record,
            "recovery_snapshot": "../review-memory-bad.tar.gz",
        },
        lambda record: {**record, "unexpected": "field"},
    ),
)
def test_inspect_rejects_invalid_record_fields(
    tmp_path: Path,
    mutator: object,
) -> None:
    marker = private_state(tmp_path) / "sandbox-quarantine.json"
    record = mutator(expected_record())  # type: ignore[operator]
    write_marker(marker, record)

    inspected = run_quarantine(*inspect_args(marker))

    assert inspected.returncode == 1


def test_duplicate_and_oversized_records_are_rejected(tmp_path: Path) -> None:
    state = private_state(tmp_path)
    duplicate = state / "duplicate.json"
    raw = json.dumps(expected_record())
    duplicate_raw = raw.replace(
        '"schema_version": 1',
        '"schema_version": 1, "schema_version": 1',
        1,
    )
    write_marker(duplicate, duplicate_raw.encode("utf-8"))
    duplicate_result = run_quarantine(*inspect_args(duplicate))
    assert duplicate_result.returncode == 1
    assert "repeats JSON field" in duplicate_result.stderr

    oversized = state / "oversized.json"
    write_marker(oversized, b" " * 32_769)
    oversized_result = run_quarantine(*inspect_args(oversized))
    assert oversized_result.returncode == 1
    assert "32768-byte limit" in oversized_result.stderr
