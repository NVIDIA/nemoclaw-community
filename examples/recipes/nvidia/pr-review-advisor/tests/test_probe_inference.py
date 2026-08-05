# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the sessionless inference readiness probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_PROBE_PATH = (
    Path(__file__).resolve().parents[1] / "agents" / "hermes" / "probe-inference.py"
)
_SPEC = importlib.util.spec_from_file_location("probe_inference", _PROBE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PROBE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PROBE)


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.read_size: int | None = None

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        self.read_size = size
        return self.body[:size]


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request: Any = None
        self.timeout: int | None = None

    def open(self, request: Any, timeout: int) -> _Response:
        self.request = request
        self.timeout = timeout
        return self.response


def test_probe_is_bounded_sessionless_and_uses_only_proxy_token() -> None:
    response = _Response(b'{"choices":[{"message":{"content":"OK"}}]}')
    opener = _Opener(response)

    _PROBE.probe("nvidia/nemotron-3-ultra-550b-a55b", opener)

    assert opener.request.full_url == (
        "https://inference.local/v1/chat/completions"
    )
    assert opener.request.get_method() == "POST"
    assert opener.request.get_header("Authorization") == (
        "Bearer sk-OPENSHELL-PROXY-REWRITE"
    )
    assert opener.timeout == 30
    assert response.read_size == _PROBE.MAX_RESPONSE_BYTES + 1
    payload = json.loads(opener.request.data)
    assert payload == {
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 1,
        "stream": False,
    }
    assert "session" not in opener.request.full_url
    assert "tools" not in payload


def test_default_opener_keeps_openshell_proxy_and_rejects_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(b'{"choices":[{"message":{"content":"OK"}}]}')
    opener = _Opener(response)
    handlers: tuple[Any, ...] = ()

    def build_opener(*provided: Any) -> _Opener:
        nonlocal handlers
        handlers = provided
        return opener

    monkeypatch.setattr(_PROBE.urllib.request, "build_opener", build_opener)

    _PROBE.probe("owner/model")

    assert len(handlers) == 1
    assert isinstance(handlers[0], _PROBE.NoRedirect)


@pytest.mark.parametrize(
    ("model", "expected_field"),
    (
        ("nvidia/nemotron-3-ultra-550b-a55b", "max_tokens"),
        ("openai/gpt-4o", "max_completion_tokens"),
        ("pipeline/openai/gpt-4.1-mini", "max_completion_tokens"),
        ("openai/gpt-5", "max_completion_tokens"),
        ("azure/o1", "max_completion_tokens"),
        ("openai/o3-mini", "max_completion_tokens"),
        ("pipeline/openai/o4-mini", "max_completion_tokens"),
    ),
)
def test_probe_matches_hermes_completion_limit_field(
    model: str,
    expected_field: str,
) -> None:
    response = _Response(b'{"choices":[{"message":{"content":"OK"}}]}')
    opener = _Opener(response)

    _PROBE.probe(model, opener)

    payload = json.loads(opener.request.data)
    assert payload[expected_field] == 1
    other_field = (
        "max_tokens"
        if expected_field == "max_completion_tokens"
        else "max_completion_tokens"
    )
    assert other_field not in payload


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        b"{}",
        b'{"choices":[]}',
        b'{"choices":["not-an-object"]}',
    ),
)
def test_probe_rejects_invalid_completion_responses(body: bytes) -> None:
    with pytest.raises(ValueError):
        _PROBE.probe("owner/model", _Opener(_Response(body)))


def test_probe_rejects_oversized_response() -> None:
    body = b"x" * (_PROBE.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        _PROBE.probe("owner/model", _Opener(_Response(body)))


def test_probe_rejects_unsafe_model_before_network() -> None:
    opener = _Opener(_Response(b'{"choices":[{}]}'))
    with pytest.raises(ValueError, match="unsafe"):
        _PROBE.probe("owner/model;touch /tmp/bad", opener)
    assert opener.request is None
