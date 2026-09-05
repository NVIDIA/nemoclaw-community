# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provenance and repository-isolation tests for trusted memory feedback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
_FEEDBACK = _EXAMPLE_ROOT / "scripts" / "feedback.sh"
_LIB = _EXAMPLE_ROOT / "scripts" / "_lib.sh"
_RECORD_FEEDBACK = _EXAMPLE_ROOT / "agents" / "hermes" / "record-feedback.py"
_CANDIDATE = "L-0123456789abcdef"
_LESSON = "Require an explicit authorization check at the request boundary."


def _scope_digest(scope: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            scope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _config_text(repository: str, scope_digest: str | None = None) -> str:
    if scope_digest is None:
        scope_digest = _artifact(repository)["run"]["scope_digest"]
    return (
        f'schema_version: 1\nrepository: "{repository}"\n'
        f'scope_digest: "{scope_digest}"\n'
    )


def _artifact(repository: str) -> dict[str, Any]:
    scope = {
        "mode": "scoped",
        "roots": ["src"],
        "support_paths": ["SECURITY.md"],
    }
    run = {
        "repository": repository,
        "base_sha": "a" * 40,
        "merge_base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "profile_digest": "d" * 64,
        "profile_source_commit": "9" * 40,
        "review_scope": scope,
        "scope_digest": _scope_digest(scope),
        "profile_path": "profiles/review.yaml",
        "profile_origin": "operator_bootstrap",
        "profile_object_id": "8" * 40,
        "acceptance_context_digest": None,
        "context_digest": "e" * 64,
        "pull_request_number": 42,
    }
    return {
        "schema_version": "review-advisor/v1",
        "run": run,
        "lesson_candidates": [
            {
                "candidate_id": _CANDIDATE,
                "status": "candidate",
                "kind": "finding_pattern",
                "statement": "Preserve the authorization boundary.",
                "rationale": "The review found a recurring authorization risk.",
                "evidence": ["src/auth.py:10-14"],
                "paths": ["src/auth.py"],
                "finding_ids": ["F-001"],
                "source": {
                    key: run[key]
                    for key in (
                        "repository",
                        "base_sha",
                        "merge_base_sha",
                        "head_sha",
                        "profile_digest",
                        "profile_source_commit",
                        "scope_digest",
                        "profile_path",
                        "profile_origin",
                        "profile_object_id",
                        "acceptance_context_digest",
                        "context_digest",
                    )
                },
            }
        ],
        "attestation": {
            "algorithm": "hmac-sha256",
            "digest": "f" * 64,
        },
    }


def _write_verified_artifact(root: Path, repository: str) -> tuple[Path, Path]:
    artifact_path = root / "review.json"
    artifact_bytes = (
        json.dumps(_artifact(repository), indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    artifact = json.loads(artifact_bytes)
    receipt = {
        "schema_version": "review-advisor-verification/v1",
        "artifact": "review.json",
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "verified": [
            "hmac-sha256",
            "trusted-request-identity",
            "hermes-session-deleted",
        ],
        "attestation_digest": artifact["attestation"]["digest"],
        "run": artifact["run"],
    }
    receipt_path = root / "verification.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_path, receipt_path


def _rewrite_verified_artifact(
    artifact_path: Path,
    receipt_path: Path,
    artifact: dict[str, Any],
) -> None:
    artifact_bytes = (
        json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifact_sha256"] = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_attestation = artifact["attestation"]
    receipt["attestation_digest"] = artifact_attestation["digest"]
    receipt["run"] = artifact["run"]
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _invoke(
    script: Path,
    artifact: Path,
    receipt: Path,
    *,
    home: Path,
    lesson: str | None = _LESSON,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home.mkdir(parents=True, exist_ok=True)
    arguments = [
        "bash",
        str(script),
        "--artifact",
        str(artifact),
        "--receipt",
        str(receipt),
        "--candidate",
        _CANDIDATE,
        "--disposition",
        "accepted",
    ]
    if lesson is not None:
        arguments.extend(("--lesson", lesson))
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            **(extra_env or {}),
        },
    )


def test_feedback_rejects_artifact_modified_after_verification(tmp_path: Path) -> None:
    artifact_path, receipt_path = _write_verified_artifact(tmp_path, "example/project")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["lesson_candidates"][0]["statement"] = "Attacker-controlled replacement."
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home",
    )

    assert result.returncode != 0
    assert "artifact changed after host verification" in result.stderr


def test_feedback_requires_a_bounded_maintainer_lesson(tmp_path: Path) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )

    missing = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-missing",
        lesson=None,
    )
    oversized = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-oversized",
        lesson="x" * 701,
    )

    assert missing.returncode != 0
    assert "--lesson is required" in missing.stderr
    assert oversized.returncode != 0
    assert "--lesson exceeds 700 characters" in oversized.stderr


def test_feedback_rejects_oversized_artifact_and_receipt(tmp_path: Path) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    artifact_path.write_bytes(b"{" + b"x" * (16 * 1024 * 1024))
    oversized_artifact = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-artifact",
    )
    assert oversized_artifact.returncode != 0
    assert "artifact exceeds 16777216 bytes" in oversized_artifact.stderr

    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    receipt_path.write_bytes(b"{" + b"x" * (64 * 1024))
    oversized_receipt = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-receipt",
    )
    assert oversized_receipt.returncode != 0
    assert "verification receipt exceeds 65536 bytes" in oversized_receipt.stderr


def test_feedback_rejects_invalid_candidate_evidence_and_source(
    tmp_path: Path,
) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["lesson_candidates"][0]["evidence"] = []
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)

    invalid_evidence = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-evidence",
    )

    assert invalid_evidence.returncode != 0
    assert "candidate evidence is invalid" in invalid_evidence.stderr

    artifact = _artifact("example/project")
    artifact["lesson_candidates"][0]["source"]["head_sha"] = "0" * 40
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)
    invalid_source = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-source",
    )

    assert invalid_source.returncode != 0
    assert "candidate source does not match artifact run: head_sha" in (
        invalid_source.stderr
    )

    artifact = _artifact("example/project")
    artifact["lesson_candidates"][0]["source"]["profile_object_id"] = "7" * 40
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)
    invalid_profile_source = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-profile-source",
    )

    assert invalid_profile_source.returncode != 0
    assert (
        "candidate source does not match artifact run: profile_object_id"
        in invalid_profile_source.stderr
    )


def test_feedback_rejects_candidate_paths_outside_strict_scope(
    tmp_path: Path,
) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["lesson_candidates"][0]["paths"] = ["docs/outside.md"]
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)

    outside = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-outside",
    )

    assert outside.returncode != 0
    assert "outside the configured review scope: docs/outside.md" in outside.stderr

    artifact = _artifact("example/project")
    artifact["lesson_candidates"][0]["paths"] = ["SECURITY.md-sibling/nested"]
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)
    nested_support = _invoke(
        _FEEDBACK,
        artifact_path,
        receipt_path,
        home=tmp_path / "home-nested-support",
    )

    assert nested_support.returncode != 0
    assert "outside the configured review scope: SECURITY.md-sibling/nested" in (
        nested_support.stderr
    )


def test_feedback_rejects_valid_artifact_from_another_repository(tmp_path: Path) -> None:
    artifact_path, receipt_path = _write_verified_artifact(tmp_path, "other/project")
    install = tmp_path / "repo" / ".nemoclaw" / "review-advisor"
    scripts = install / "runtime" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(_FEEDBACK, scripts / "feedback.sh")
    shutil.copy2(_LIB, scripts / "_lib.sh")
    (install / "config.yaml").write_text(
        _config_text("expected/project"),
        encoding="utf-8",
    )
    env_path = install / ".env"
    env_path.write_text(
        "OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    result = _invoke(
        scripts / "feedback.sh",
        artifact_path,
        receipt_path,
        home=tmp_path / "home",
    )

    assert result.returncode != 0
    assert "belongs to other/project, not this installation" in result.stderr


def test_feedback_rejects_valid_artifact_from_another_scope(tmp_path: Path) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    install = tmp_path / "repo" / ".nemoclaw" / "review-advisor"
    scripts = install / "runtime" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(_FEEDBACK, scripts / "feedback.sh")
    shutil.copy2(_LIB, scripts / "_lib.sh")
    (install / "config.yaml").write_text(
        _config_text("example/project", "0" * 64),
        encoding="utf-8",
    )
    env_path = install / ".env"
    env_path.write_text(
        "OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    result = _invoke(
        scripts / "feedback.sh",
        artifact_path,
        receipt_path,
        home=tmp_path / "home",
    )

    assert result.returncode != 0
    assert "belongs to a different configured review scope" in result.stderr


def test_feedback_uploads_only_the_curated_lesson_and_candidate_provenance(
    tmp_path: Path,
) -> None:
    artifact_path, receipt_path = _write_verified_artifact(
        tmp_path,
        "example/project",
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["lesson_candidates"][0]["paths"] = [
        "SECURITY.md/controls/authorization.md"
    ]
    _rewrite_verified_artifact(artifact_path, receipt_path, artifact)
    install = tmp_path / "repo" / ".nemoclaw" / "review-advisor"
    runtime = install / "runtime"
    shutil.copytree(
        _EXAMPLE_ROOT,
        runtime,
        ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__", "*.pyc"),
    )
    scripts = runtime / "scripts"
    (install / "config.yaml").write_text(
        _config_text("example/project"),
        encoding="utf-8",
    )
    env_path = install / ".env"
    env_path.write_text(
        "NEMOCLAW_SANDBOX_NAME=test-feedback-sandbox\n"
        "OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    identity = subprocess.run(
        [
            "bash",
            "-c",
            (
                'source "$1"; load_env; compute_runtime_fingerprint; '
                'printf "%s\\n%s\\n" "$OPENSHELL_GATEWAY" '
                '"$REVIEW_ADVISOR_RUNTIME_FINGERPRINT"'
            ),
            "bash",
            str(scripts / "_lib.sh"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )
    assert identity.returncode == 0, identity.stderr
    gateway_name, runtime_fingerprint = identity.stdout.splitlines()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_openshell = fake_bin / "openshell"
    fake_openshell.write_text(
        """#!/usr/bin/env bash
set -eu
if [[ "${1:-}" == "-V" ]]; then
  printf 'openshell 0.0.85\\n'
  exit 0
fi
gateway=""
if [[ "${1:-}" == "-g" ]]; then
  gateway="$2"
  shift 2
fi
if [[ "$1 $2" == "gateway list" ]]; then
  printf '[{"name":"%s","endpoint":"https://127.0.0.1:17670"}]\\n' "$FAKE_GATEWAY_NAME"
elif [[ "$1 $2" == "gateway info" ]]; then
  printf '{"gateway":"%s","server":"https://127.0.0.1:17670"}\\n' "$gateway"
elif [[ "$1 $2" == "sandbox list" ]]; then
  printf '[{"name":"test-feedback-sandbox","phase":"Ready"}]\\n'
elif [[ "$1 $2" == "sandbox upload" ]]; then
  cp "$5" "$FAKE_FEEDBACK_CAPTURE"
elif [[ "$1 $2" == "sandbox exec" && "$*" == *"runtime-fingerprint"* ]]; then
  printf '%s\\n' "$FAKE_RUNTIME_FINGERPRINT"
elif [[ "$1 $2" == "sandbox exec" ]]; then
  printf '{"success": true}\\n'
else
  exit 2
fi
""",
        encoding="utf-8",
    )
    fake_openshell.chmod(0o755)
    capture = tmp_path / "feedback-payload.json"

    result = _invoke(
        scripts / "feedback.sh",
        artifact_path,
        receipt_path,
        home=tmp_path / "home",
        lesson="  Require an explicit authorization check   at the boundary. ",
        extra_env={
            "FAKE_FEEDBACK_CAPTURE": str(capture),
            "FAKE_GATEWAY_NAME": gateway_name,
            "FAKE_RUNTIME_FINGERPRINT": runtime_fingerprint,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(capture.read_text(encoding="utf-8"))
    assert payload["lesson"] == (
        "Require an explicit authorization check at the boundary."
    )
    assert payload["candidate_id"] == _CANDIDATE
    assert payload["paths"] == ["SECURITY.md/controls/authorization.md"]
    assert payload["review_scope"] == {
        "mode": "scoped",
        "roots": ["src"],
        "support_paths": ["SECURITY.md"],
    }
    assert payload["scope_digest"] == _scope_digest(payload["review_scope"])
    assert payload["profile_path"] == "profiles/review.yaml"
    assert payload["profile_origin"] == "operator_bootstrap"
    assert payload["profile_object_id"] == "8" * 40
    assert payload["evidence_digest"] == hashlib.sha256(
        b'["src/auth.py:10-14"]'
    ).hexdigest()
    assert "statement" not in payload
    assert "rationale" not in payload
    assert "evidence" not in payload
    assert "Preserve the authorization boundary." not in capture.read_text(
        encoding="utf-8",
    )


def _feedback_payload() -> dict[str, Any]:
    scope = {
        "mode": "scoped",
        "roots": ["src"],
        "support_paths": ["SECURITY.md"],
    }
    return {
        "repository": "example/project",
        "base_sha": "a" * 40,
        "merge_base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "profile_digest": "d" * 64,
        "profile_source_commit": "9" * 40,
        "review_scope": scope,
        "scope_digest": _scope_digest(scope),
        "profile_path": "profiles/review.yaml",
        "profile_origin": "operator_bootstrap",
        "profile_object_id": "8" * 40,
        "acceptance_context_digest": None,
        "context_digest": "e" * 64,
        "candidate_id": _CANDIDATE,
        "disposition": "accepted",
        "lesson": _LESSON,
        "paths": ["src/auth.py"],
        "evidence_digest": "f" * 64,
    }


def test_record_feedback_persists_curated_lesson_not_candidate_statement(
    tmp_path: Path,
) -> None:
    stub_root = tmp_path / "stub"
    tools = stub_root / "tools"
    tools.mkdir(parents=True)
    (tools / "__init__.py").write_text("", encoding="utf-8")
    (tools / "memory_tool.py").write_text(
        """import json
import os
from pathlib import Path

class MemoryStore:
    def load_from_disk(self):
        return None

    def add(self, category, content):
        Path(os.environ["MEMORY_CAPTURE"]).write_text(
            json.dumps({"category": category, "content": content}),
            encoding="utf-8",
        )
        return {"success": True}
""",
        encoding="utf-8",
    )
    payload_path = tmp_path / "feedback.json"
    payload_path.write_text(
        json.dumps(_feedback_payload()),
        encoding="utf-8",
    )
    capture = tmp_path / "memory.json"

    result = subprocess.run(
        [sys.executable, str(_RECORD_FEEDBACK), str(payload_path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(stub_root),
            "MEMORY_CAPTURE": str(capture),
        },
    )

    assert result.returncode == 0, result.stderr
    stored = json.loads(capture.read_text(encoding="utf-8"))
    assert stored["category"] == "memory"
    assert stored["content"].startswith(_LESSON)
    assert "candidate=L-0123456789abcdef" in stored["content"]
    assert "candidate_evidence=" + ("f" * 64) in stored["content"]
    assert "scope=" + _scope_digest(_feedback_payload()["review_scope"]) in stored[
        "content"
    ]
    assert "profile_path=profiles/review.yaml" in stored["content"]
    assert "profile_origin=operator_bootstrap" in stored["content"]
    assert "profile_object=" + ("8" * 40) in stored["content"]
    assert "Preserve the authorization boundary." not in stored["content"]

    payload = _feedback_payload()
    payload["statement"] = "Model-authored text must not cross this boundary."
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(_RECORD_FEEDBACK), str(payload_path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(stub_root),
            "MEMORY_CAPTURE": str(capture),
        },
    )
    assert rejected.returncode != 0
    assert "invalid shape" in rejected.stdout

    payload = _feedback_payload()
    payload["paths"] = ["docs/outside.md"]
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    outside = subprocess.run(
        [sys.executable, str(_RECORD_FEEDBACK), str(payload_path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(stub_root),
            "MEMORY_CAPTURE": str(capture),
        },
    )
    assert outside.returncode != 0
    assert "outside the configured review scope" in outside.stdout

    payload = _feedback_payload()
    payload["paths"] = ["SECURITY.md-sibling/nested"]
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    sibling = subprocess.run(
        [sys.executable, str(_RECORD_FEEDBACK), str(payload_path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(stub_root),
            "MEMORY_CAPTURE": str(capture),
        },
    )
    assert sibling.returncode != 0
    assert "outside the configured review scope" in sibling.stdout

    payload = _feedback_payload()
    payload["paths"] = ["SECURITY.md/controls/authorization.md"]
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    support_descendant = subprocess.run(
        [sys.executable, str(_RECORD_FEEDBACK), str(payload_path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(stub_root),
            "MEMORY_CAPTURE": str(capture),
        },
    )
    assert support_descendant.returncode == 0, support_descendant.stdout


def test_lifecycle_auth_state_defaults_outside_repository_checkout(
    tmp_path: Path,
) -> None:
    install = tmp_path / "repo" / ".nemoclaw" / "review-advisor"
    scripts = install / "runtime" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(_LIB, scripts / "_lib.sh")
    (install / "config.yaml").write_text(
        _config_text("example/project"),
        encoding="utf-8",
    )
    env_path = install / ".env"
    env_path.write_text(
        "OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    for name in (
        "REVIEW_ADVISOR_STATE_DIR",
        "REVIEW_ADVISOR_STATE_ROOT",
        "REVIEW_ADVISOR_SNAPSHOT_DIR",
        "XDG_STATE_HOME",
    ):
        env.pop(name, None)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; load_env; printf "%s\\n%s\\n" "$STATE_DIR" "$SNAPSHOT_DIR"',
            "bash",
            str(scripts / "_lib.sh"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    state_dir, snapshot_dir = result.stdout.splitlines()
    expected_root = tmp_path / "home" / ".local" / "state" / "nemoclaw-review-advisor"
    assert Path(state_dir).is_relative_to(expected_root)
    assert Path(snapshot_dir).is_relative_to(expected_root)
    assert not Path(state_dir).is_relative_to(install)
