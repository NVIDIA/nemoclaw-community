# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


RECIPE_DIR = Path(__file__).resolve().parents[2]
RELAY_PATH = RECIPE_DIR / "extras/atif-export-relay/relay.py"
START_PATH = RECIPE_DIR / "agents/hermes/start.sh"


class FakeBackendError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class FakeBackendTransportError(Exception):
    pass


class RecordingBackend:
    label = "test"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes, str | None]] = []
        self.failure: Exception | None = None

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None,
    ) -> Any:
        self.calls.append((bucket, key, body, content_type))
        if self.failure is not None:
            raise self.failure
        return types.SimpleNamespace(etag="test-etag", key=f"prefix/{key}")

    def health_probe(self) -> str:
        return "test credentials"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_relay(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, RecordingBackend]:
    backend = RecordingBackend()
    fake_backends = types.ModuleType("backends")
    fake_backends.BackendError = FakeBackendError
    fake_backends.BackendTransportError = FakeBackendTransportError
    fake_backends.build_backend = lambda _name: backend
    monkeypatch.setitem(sys.modules, "backends", fake_backends)
    monkeypatch.setenv("ATIF_RELAY_DOWNSTREAM", "test")
    monkeypatch.setenv("ATIF_RELAY_BUCKET", "relay-owned-bucket")
    monkeypatch.setenv("ATIF_RELAY_AUTH_TOKEN", "expected-token")
    module = _load_module(RELAY_PATH, f"test_atif_relay_{id(backend)}")
    return module, backend


async def _with_client(app: web.Application, callback) -> None:
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        await callback(client)
    finally:
        await client.close()


def test_relay_requires_the_configured_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    relay, backend = _load_relay(monkeypatch)

    async def scenario(client: TestClient) -> None:
        for authorization in (None, "Basic expected-token", "Bearer wrong-token"):
            headers = {"X-NeMo-Relay-ATIF-Filename": "trajectory.json"}
            if authorization is not None:
                headers["Authorization"] = authorization
            response = await client.post("/atif", headers=headers, data=b"{}")
            assert response.status == 403

    asyncio.run(_with_client(relay.make_app(), scenario))
    assert backend.calls == []


def test_relay_forwards_native_post_and_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    relay, backend = _load_relay(monkeypatch)
    payload = b'{"schema_version":"ATIF-v1.7"}'

    async def scenario(client: TestClient) -> None:
        response = await client.get("/atif")
        assert response.status == 405

        response = await client.post(
            "/atif",
            headers={
                "Authorization": "Bearer expected-token",
                "Content-Type": "application/json",
                "X-NeMo-Relay-ATIF-Filename": "hermes-atif-session.json",
                "X-NeMo-Relay-ATIF-Session-ID": "session",
            },
            data=payload,
        )
        assert response.status == 204

    asyncio.run(_with_client(relay.make_app(), scenario))
    assert backend.calls == [
        (
            "relay-owned-bucket",
            "hermes-atif-session.json",
            payload,
            "application/json",
        )
    ]


def test_start_uses_the_provider_injected_relay_placeholder() -> None:
    source = START_PATH.read_text(encoding="utf-8")
    expected = (
        "Bearer ${ATIF_RELAY_AUTH_TOKEN:-"
        "openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN}"
    )
    assert source.count(expected) == 2


@pytest.mark.parametrize("filename", ["", "../escape.json", "/absolute.json", "bad\\name.json"])
def test_relay_rejects_unsafe_filenames(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    relay, backend = _load_relay(monkeypatch)

    async def scenario(client: TestClient) -> None:
        response = await client.post(
            "/atif",
            headers={
                "Authorization": "Bearer expected-token",
                "X-NeMo-Relay-ATIF-Filename": filename,
            },
            data=b"{}",
        )
        assert response.status == 400

    asyncio.run(_with_client(relay.make_app(), scenario))
    assert backend.calls == []


def test_relay_translates_downstream_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    relay, backend = _load_relay(monkeypatch)

    async def scenario(client: TestClient) -> None:
        headers = {
            "Authorization": "Bearer expected-token",
            "X-NeMo-Relay-ATIF-Filename": "trajectory.json",
        }

        backend.failure = FakeBackendError(409, "BucketConflict", "cannot write")
        response = await client.post("/atif", headers=headers, data=b"{}")
        assert response.status == 409
        assert "BucketConflict" in await response.text()

        backend.failure = FakeBackendTransportError("connection refused")
        response = await client.post("/atif", headers=headers, data=b"{}")
        assert response.status == 502
        assert "downstream unreachable" in await response.text()

    asyncio.run(_with_client(relay.make_app(), scenario))
