# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render deleted-line locations without implying they exist at the head."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
_CALL_HERMES = _EXAMPLE_ROOT / "scripts" / "call-hermes.py"
_PUBLISH = _EXAMPLE_ROOT / "scripts" / "publish.sh"


def _load_call_hermes() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "review_advisor_call_hermes_renderer_test",
        _CALL_HERMES,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scope_digest(scope: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            scope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _artifact() -> dict[str, Any]:
    scope = {
        "mode": "scoped",
        "roots": ["policy"],
        "support_paths": ["SECURITY.md"],
    }
    return {
        "schema_version": "review-advisor/v1",
        "run": {
            "repository": "example/project",
            "base_sha": "a" * 40,
            "merge_base_sha": "b" * 40,
            "profile_source_commit": "9" * 40,
            "head_sha": "c" * 40,
            "profile_digest": "d" * 64,
            "review_scope": scope,
            "scope_digest": _scope_digest(scope),
            "profile_path": "profiles/review.yaml",
            "profile_origin": "operator_bootstrap",
            "profile_object_id": "8" * 40,
            "acceptance_context_digest": None,
            "context_digest": "e" * 64,
            "pull_request_number": 42,
        },
        "summary": {
            "recommendation": "changes_requested",
            "confidence": "high",
            "one_line": "A required policy was deleted.",
        },
        "findings": [
            {
                "id": "F-001",
                "severity": "blocker",
                "side": "base",
                "file": "policy/authorization.yaml",
                "line": 4,
                "title": "Authorization policy removed",
                "description": "The only authorization policy was deleted.",
                "impact": "Requests can bypass the expected policy.",
                "recommendation": "Restore the policy.",
            }
        ],
        "limitations": [],
        "attestation": {
            "algorithm": "hmac-sha256",
            "digest": "f" * 64,
        },
    }


def test_local_markdown_labels_base_side_locations() -> None:
    module = _load_call_hermes()
    rendered = module.markdown(_artifact())

    assert "`policy/authorization.yaml:4` (`base` side)" in rendered
    assert "Provisional operator-bootstrap review" in rendered
    assert "**Changed-path roots:** `policy`" in rendered
    assert "**Read-only support paths:** `SECURITY.md`" in rendered
    assert "**Profile origin:** `operator_bootstrap`" in rendered
    assert f"**Profile blob:** `{'8' * 40}`" in rendered


def test_local_markdown_target_base_profile_is_not_provisional() -> None:
    module = _load_call_hermes()
    artifact = _artifact()
    artifact["run"]["profile_origin"] = "target_base"

    rendered = module.markdown(artifact)

    assert "Provisional operator-bootstrap review" not in rendered


def test_local_markdown_renders_model_text_as_literal_content() -> None:
    module = _load_call_hermes()
    artifact = _artifact()
    artifact["summary"]["one_line"] = (
        "<img src=x onerror=alert(1)> @octocat [click](https://example.invalid)"
    )
    artifact["findings"][0].update(
        {
            "title": "Do not ping @security-team\n## injected",
            "file": "src/`escape`.py",
            "description": "<script>alert(1)</script>\n> quote",
            "impact": "@owners **bold**",
            "recommendation": "[link](https://example.invalid)",
        }
    )
    artifact["limitations"] = [{"description": "<b>@admins</b>"}]

    rendered = module.markdown(artifact)

    assert "<img" not in rendered
    assert "<script>" not in rendered
    assert "<b>" not in rendered
    assert "@octocat" not in rendered
    assert "@security-team" not in rendered
    assert "@\u200boctocat" in rendered
    assert "@\u200bsecurity\\-team" in rendered
    assert "](https://" not in rendered
    assert "&lt;img src=x onerror=alert\\(1\\)&gt;" in rendered
    assert "``src/`escape`.py:4``" in rendered


def test_publisher_labels_base_side_and_scrubs_inference_keys(tmp_path: Path) -> None:
    artifact_path = tmp_path / "review.json"
    artifact_value = _artifact()
    artifact_value["summary"]["one_line"] = (
        "<img src=x onerror=alert(1)> @octocat [click](https://example.invalid)"
    )
    artifact_value["findings"][0]["title"] = "Do not ping @security-team"
    artifact_bytes = (
        json.dumps(artifact_value, indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    artifact = json.loads(artifact_bytes)
    receipt_path = tmp_path / "verification.json"
    receipt_path.write_text(
        json.dumps(
            {
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
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import os
import json
import pathlib
import sys

args = sys.argv[1:]
capture = pathlib.Path(os.environ["FAKE_GH_CAPTURE"])
if args[:1] == ["api"] and any("@tsv" in arg for arg in args):
    print("open\\t" + "a" * 40 + "\\t" + "c" * 40)
elif args[:1] == ["api"]:
    print("c" * 40)
elif args[:2] == ["pr", "comment"]:
    body = pathlib.Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
    capture.write_text(body, encoding="utf-8")
    names = (
        "NVIDIA_INFERENCE_API_KEY", "NVIDIA_API_KEY", "NGC_API_KEY",
        "COMPATIBLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY", "TOGETHER_API_KEY", "GROQ_API_KEY",
        "MISTRAL_API_KEY", "COHERE_API_KEY", "GOOGLE_API_KEY",
        "GEMINI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_API_KEY",
        "DEEPINFRA_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    )
    capture.with_suffix(".env").write_text(
        json.dumps({name: os.environ.get(name) for name in names}, sort_keys=True),
        encoding="utf-8",
    )
else:
    raise SystemExit(f"unexpected gh arguments: {args!r}")
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    capture = tmp_path / "published.md"
    result = subprocess.run(
        [
            "bash",
            str(_PUBLISH),
            "--artifact",
            str(artifact_path),
            "--receipt",
            str(receipt_path),
            "--repo",
            "example/project",
            "--pr",
            "42",
            "--head",
            "c" * 40,
            "--confirm-publish",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_CAPTURE": str(capture),
            **{
                name: "must-not-reach-gh"
                for name in (
                    "NVIDIA_INFERENCE_API_KEY",
                    "NVIDIA_API_KEY",
                    "NGC_API_KEY",
                    "COMPATIBLE_API_KEY",
                    "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY",
                    "OPENROUTER_API_KEY",
                    "TOGETHER_API_KEY",
                    "GROQ_API_KEY",
                    "MISTRAL_API_KEY",
                    "COHERE_API_KEY",
                    "GOOGLE_API_KEY",
                    "GEMINI_API_KEY",
                    "AZURE_OPENAI_API_KEY",
                    "AZURE_API_KEY",
                    "DEEPINFRA_API_KEY",
                    "HF_TOKEN",
                    "HUGGING_FACE_HUB_TOKEN",
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "AWS_SESSION_TOKEN",
                )
            },
        },
    )

    assert result.returncode == 0, result.stderr
    assert "`policy/authorization.yaml:4` (`base` side)" in capture.read_text(
        encoding="utf-8"
    )
    rendered = capture.read_text(encoding="utf-8")
    assert "Provisional operator-bootstrap review" in rendered
    assert "**Changed-path roots:** `policy`" in rendered
    assert "**Read-only support paths:** `SECURITY.md`" in rendered
    assert "**Profile origin:** `operator_bootstrap`" in rendered
    assert f"**Profile blob:** `{'8' * 40}`" in rendered
    assert "@octocat" not in rendered
    assert "@security-team" not in rendered
    assert "@\u200boctocat" in rendered
    assert "@\u200bsecurity\\-team" in rendered
    assert "<img" not in rendered
    assert "&lt;img src=x onerror=alert\\(1\\)&gt;" in rendered
    assert "](https://" not in rendered
    assert set(json.loads(capture.with_suffix(".env").read_text()).values()) == {None}


def test_publisher_rejects_oversized_comment_before_github_write(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["summary"]["one_line"] = "x" * 70_000
    artifact_path = tmp_path / "review.json"
    artifact_bytes = (
        json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    receipt_path = tmp_path / "verification.json"
    receipt_path.write_text(
        json.dumps(
            {
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
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nexit 99\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            str(_PUBLISH),
            "--artifact",
            str(artifact_path),
            "--receipt",
            str(receipt_path),
            "--repo",
            "example/project",
            "--pr",
            "42",
            "--head",
            "c" * 40,
            "--confirm-publish",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert "61440-byte publication limit" in result.stderr


def test_publisher_receipt_binds_scope_and_profile_identity(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact_path = tmp_path / "review.json"
    artifact_bytes = (
        json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    receipt_path = tmp_path / "verification.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "gh-called"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        f"#!/usr/bin/env bash\nprintf called >{marker!s}\nexit 99\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    for field in (
        "review_scope",
        "scope_digest",
        "profile_path",
        "profile_origin",
        "profile_object_id",
    ):
        receipt_run = dict(artifact["run"])
        receipt_run.pop(field)
        receipt_path.write_text(
            json.dumps(
                {
                    "schema_version": "review-advisor-verification/v1",
                    "artifact": "review.json",
                    "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                    "verified": [
                        "hmac-sha256",
                        "trusted-request-identity",
                        "hermes-session-deleted",
                    ],
                    "attestation_digest": artifact["attestation"]["digest"],
                    "run": receipt_run,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "bash",
                str(_PUBLISH),
                "--artifact",
                str(artifact_path),
                "--receipt",
                str(receipt_path),
                "--repo",
                "example/project",
                "--pr",
                "42",
                "--head",
                "c" * 40,
                "--confirm-publish",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            },
        )

        assert result.returncode != 0
        assert "receipt run identity does not match artifact" in result.stderr
        assert not marker.exists()


def test_publisher_rejects_oversized_artifact_before_github_write(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "review.json"
    artifact_path.write_bytes(b"{" + b"x" * (16 * 1024 * 1024))
    receipt_path = tmp_path / "verification.json"
    receipt_path.write_text("{}\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "gh-called"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        f"#!/usr/bin/env bash\nprintf called >{marker!s}\nexit 99\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            str(_PUBLISH),
            "--artifact",
            str(artifact_path),
            "--receipt",
            str(receipt_path),
            "--repo",
            "example/project",
            "--pr",
            "42",
            "--head",
            "c" * 40,
            "--confirm-publish",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert "artifact exceeds 16777216 bytes" in result.stderr
    assert not marker.exists()


def test_publisher_refreshes_and_matches_acceptance_before_write(
    tmp_path: Path,
) -> None:
    acceptance_bytes = (
        json.dumps(
            {
                "schema_version": "review-advisor/pr-acceptance/v1",
                "repository": "example/project",
                "pull_request_number": 42,
                "base_sha": "a" * 40,
                "head_sha": "c" * 40,
                "pull_request": {"title": "Current", "body": ""},
                "closing_issues": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    result, capture = _run_acceptance_publish(
        tmp_path,
        reviewed_acceptance=acceptance_bytes,
        live_acceptance=acceptance_bytes,
    )

    assert result.returncode == 0, result.stderr
    assert capture.is_file()
    assert (tmp_path / "fetch-token.txt").read_text(encoding="utf-8") == (
        "test-token"
    )


def test_publisher_rejects_changed_acceptance_before_write(
    tmp_path: Path,
) -> None:
    reviewed = b'{"body":"reviewed"}\n'
    changed = b'{"body":"changed"}\n'
    result, capture = _run_acceptance_publish(
        tmp_path,
        reviewed_acceptance=reviewed,
        live_acceptance=changed,
    )

    assert result.returncode != 0
    assert "acceptance context changed after review" in result.stderr
    assert not capture.exists()


def _run_acceptance_publish(
    tmp_path: Path,
    *,
    reviewed_acceptance: bytes,
    live_acceptance: bytes,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    artifact = _artifact()
    artifact["run"]["acceptance_context_digest"] = hashlib.sha256(
        reviewed_acceptance
    ).hexdigest()
    artifact_path = tmp_path / "review.json"
    artifact_bytes = (
        json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    ).encode()
    artifact_path.write_bytes(artifact_bytes)
    receipt_path = tmp_path / "verification.json"
    receipt_path.write_text(
        json.dumps(
            {
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
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    live_acceptance_path = tmp_path / "live-source.json"
    live_acceptance_path.write_bytes(live_acceptance)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        f"""#!{sys.executable}
import os
import pathlib
import shutil
import sys

args = sys.argv[1:]
if args and args[0].endswith("fetch-pr-context.py"):
    output = pathlib.Path(args[args.index("--output") + 1])
    shutil.copyfile(os.environ["FAKE_ACCEPTANCE_SOURCE"], output)
    pathlib.Path(os.environ["FAKE_TOKEN_CAPTURE"]).write_text(
        os.environ.get("NEMOCLAW_GITHUB_TOKEN", ""),
        encoding="utf-8",
    )
    raise SystemExit(0)
os.execv({sys.executable!r}, [{sys.executable!r}, *args])
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import sys

args = sys.argv[1:]
if args[:2] == ["auth", "token"]:
    print("test-token")
elif args[:2] == ["pr", "comment"]:
    body = pathlib.Path(args[args.index("--body-file") + 1]).read_text(
        encoding="utf-8"
    )
    pathlib.Path(os.environ["FAKE_GH_CAPTURE"]).write_text(body, encoding="utf-8")
else:
    raise SystemExit(f"unexpected gh arguments: {args!r}")
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    capture = tmp_path / "published.md"

    result = subprocess.run(
        [
            "bash",
            str(_PUBLISH),
            "--artifact",
            str(artifact_path),
            "--receipt",
            str(receipt_path),
            "--repo",
            "example/project",
            "--pr",
            "42",
            "--head",
            "c" * 40,
            "--confirm-publish",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_ACCEPTANCE_SOURCE": str(live_acceptance_path),
            "FAKE_TOKEN_CAPTURE": str(tmp_path / "fetch-token.txt"),
            "FAKE_GH_CAPTURE": str(capture),
        },
    )
    return result, capture
