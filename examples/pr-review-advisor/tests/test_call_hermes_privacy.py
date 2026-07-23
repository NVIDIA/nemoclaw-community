# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed Hermes session cleanup and private artifact staging tests."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import os
import stat
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
_CALL_HERMES = _EXAMPLE_ROOT / "scripts" / "call-hermes.py"
_SESSION_ID = "review-cccccccccccc-0123456789ab"
_API_KEY = "a" * 40


def _request_identity() -> dict[str, Any]:
    return {
        "repository": "example/project",
        "base_sha": "a" * 40,
        "merge_base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "profile_digest": "d" * 64,
        "profile_source_commit": "9" * 40,
        "acceptance_context_digest": None,
        "context_digest": "e" * 64,
        "pull_request_number": 42,
    }


def _artifact(key: bytes) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "schema_version": "review-advisor/v1",
        "run": _request_identity(),
        "summary": {
            "recommendation": "approve",
            "confidence": "high",
            "one_line": "No actionable findings.",
        },
        "findings": [],
        "ledger": [],
        "stage_receipts": [],
        "positives": [],
        "limitations": [],
        "lesson_candidates": [],
    }
    canonical = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    artifact["attestation"] = {
        "algorithm": "hmac-sha256",
        "digest": hmac.new(key, canonical, hashlib.sha256).hexdigest(),
    }
    return artifact


@contextmanager
def _server(
    artifact: dict[str, Any],
    *,
    chat_status: int = 200,
    delete_confirmed: bool = True,
    redirect: str | None = None,
    oversized_chat: bool = False,
) -> Iterator[tuple[str, list[tuple[str, str | None]]]]:
    calls: list[tuple[str, str | None]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, status_code: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode()
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            calls.append(("POST", self.headers.get("Authorization")))
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if redirect is not None:
                self.send_response(307)
                self.send_header("Location", redirect)
                self.send_header("X-Hermes-Session-Id", _SESSION_ID)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(chat_status)
            self.send_header("X-Hermes-Session-Id", _SESSION_ID)
            payload = (
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(artifact, sort_keys=True),
                            }
                        }
                    ]
                }
                if chat_status == 200
                else {"error": {"message": "forced chat failure"}}
            )
            encoded = (
                b"x" * (16 * 1024 * 1024 + 1)
                if oversized_chat
                else json.dumps(payload).encode()
            )
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_DELETE(self) -> None:  # noqa: N802
            calls.append(("DELETE", self.headers.get("Authorization")))
            self._json(
                200,
                {
                    "object": "hermes.session.deleted",
                    "id": _SESSION_ID,
                    "deleted": delete_confirmed,
                },
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", calls
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _invoke(
    tmp_path: Path,
    url: str,
    artifact: dict[str, Any],
    key: bytes,
) -> subprocess.CompletedProcess[str]:
    api_key_file = tmp_path / "api-key"
    api_key_file.write_text(_API_KEY, encoding="ascii")
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(_request_identity(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    attestation_key = tmp_path / "attestation.key"
    attestation_key.write_bytes(key)
    return subprocess.run(
        [
            "python3",
            str(_CALL_HERMES),
            "--url",
            url,
            "--api-key-file",
            str(api_key_file),
            "--session-id",
            _SESSION_ID,
            "--request",
            str(request_path),
            "--attestation-key-file",
            str(attestation_key),
            "--output",
            str(tmp_path / "output"),
            "--timeout",
            "5",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
            "no_proxy": "",
        },
    )


def test_success_deletes_authenticated_session_before_private_artifacts(
    tmp_path: Path,
) -> None:
    key = bytes(range(32))
    artifact = _artifact(key)
    with _server(artifact) as (url, calls):
        result = _invoke(tmp_path, url, artifact, key)

    assert result.returncode == 0, result.stderr
    assert calls == [
        ("POST", f"Bearer {_API_KEY}"),
        ("DELETE", f"Bearer {_API_KEY}"),
    ]
    output = tmp_path / "output"
    assert not (output / "hermes-response.json").exists()
    assert json.loads((output / "verification.json").read_text())["verified"] == [
        "hmac-sha256",
        "trusted-request-identity",
        "hermes-session-deleted",
    ]
    assert json.loads((output / ".session-cleanup.json").read_text())[
        "deleted_session_ids"
    ] == [_SESSION_ID]
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for name in ("review.json", "review.md", "verification.json"):
        assert stat.S_IMODE((output / name).stat().st_mode) == 0o600


def test_deletion_failure_prevents_canonical_artifacts(tmp_path: Path) -> None:
    key = bytes(range(32))
    artifact = _artifact(key)
    with _server(artifact, delete_confirmed=False) as (url, calls):
        result = _invoke(tmp_path, url, artifact, key)

    assert result.returncode != 0
    assert calls == [
        ("POST", f"Bearer {_API_KEY}"),
        ("DELETE", f"Bearer {_API_KEY}"),
    ]
    assert "not positively confirmed" in result.stderr
    output = tmp_path / "output"
    assert not (output / "review.json").exists()
    assert not (output / "verification.json").exists()
    assert not (output / "hermes-response.json").exists()


def test_chat_failure_still_deletes_session_without_artifacts(tmp_path: Path) -> None:
    key = bytes(range(32))
    artifact = _artifact(key)
    with _server(artifact, chat_status=500) as (url, calls):
        result = _invoke(tmp_path, url, artifact, key)

    assert result.returncode != 0
    assert calls == [
        ("POST", f"Bearer {_API_KEY}"),
        ("DELETE", f"Bearer {_API_KEY}"),
    ]
    assert "Hermes returned HTTP 500" in result.stderr
    output = tmp_path / "output"
    assert (output / ".session-cleanup.json").is_file()
    assert not (output / "review.json").exists()
    assert not (output / "verification.json").exists()


def test_oversized_chat_is_rejected_after_authenticated_session_delete(
    tmp_path: Path,
) -> None:
    key = bytes(range(32))
    artifact = _artifact(key)
    with _server(artifact, oversized_chat=True) as (url, calls):
        result = _invoke(tmp_path, url, artifact, key)

    assert result.returncode != 0
    assert calls == [
        ("POST", f"Bearer {_API_KEY}"),
        ("DELETE", f"Bearer {_API_KEY}"),
    ]
    assert "Hermes chat response exceeds 16777216 bytes" in result.stderr
    output = tmp_path / "output"
    assert (output / ".session-cleanup.json").is_file()
    assert not (output / "review.json").exists()


def test_redirect_is_not_followed_and_session_is_still_deleted(
    tmp_path: Path,
) -> None:
    key = bytes(range(32))
    artifact = _artifact(key)
    redirected_calls: list[str] = []

    class RedirectTarget(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            redirected_calls.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)
    thread = threading.Thread(target=target.serve_forever, daemon=True)
    thread.start()
    try:
        target_url = f"http://127.0.0.1:{target.server_address[1]}/capture"
        with _server(artifact, redirect=target_url) as (url, calls):
            result = _invoke(tmp_path, url, artifact, key)
    finally:
        target.shutdown()
        thread.join(timeout=5)
        target.server_close()

    assert result.returncode != 0
    assert redirected_calls == []
    assert calls == [
        ("POST", f"Bearer {_API_KEY}"),
        ("DELETE", f"Bearer {_API_KEY}"),
    ]
    assert "HTTP 307" in result.stderr
