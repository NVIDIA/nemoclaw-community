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
BRIDGE_PATH = RECIPE_DIR / "agents/hermes/bridges/atif/atif-bridge.py"
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


def _load_bridge(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "ATIF_RELAY_AUTH_TOKEN",
        "ATIF_RELAY_AUTHORIZATION",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    return _load_module(BRIDGE_PATH, f"test_atif_bridge_{id(monkeypatch)}")


def test_bridge_preserves_native_request_without_hop_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _load_bridge(monkeypatch)
    received: dict[str, Any] = {}
    payload = b'{"schema_version":"ATIF-v1.7"}'

    async def scenario() -> None:
        async def upstream_handler(request: web.Request) -> web.Response:
            received.update(
                method=request.method,
                path_qs=request.path_qs,
                headers=dict(request.headers),
                body=await request.read(),
            )
            return web.Response(status=202, body=b"stored", headers={"X-Upstream": "ok"})

        upstream_app = web.Application()
        upstream_app.router.add_route("*", "/{tail:.*}", upstream_handler)
        upstream_server = TestServer(upstream_app)
        await upstream_server.start_server()
        bridge.UPSTREAM = str(upstream_server.make_url("/")).rstrip("/")

        client = TestClient(TestServer(bridge.make_app()))
        await client.start_server()
        try:
            response = await client.post(
                "/atif?source=native",
                headers={
                    "Authorization": "Bearer openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN",
                    "Host": "sandbox.invalid",
                    "X-NeMo-Relay-ATIF-Filename": "trajectory.json",
                },
                data=payload,
            )
            assert response.status == 202
            assert await response.read() == b"stored"
            assert response.headers["X-Upstream"] == "ok"
        finally:
            await client.close()
            await upstream_server.close()

    asyncio.run(scenario())
    assert received["method"] == "POST"
    assert received["path_qs"] == "/atif?source=native"
    assert received["body"] == payload
    assert received["headers"]["Authorization"] == (
        "Bearer openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN"
    )
    assert received["headers"]["X-NeMo-Relay-ATIF-Filename"] == "trajectory.json"
    assert received["headers"]["Host"] != "sandbox.invalid"


@pytest.mark.parametrize("leak_name", ["ATIF_RELAY_AUTH_TOKEN", "ATIF_RELAY_AUTHORIZATION"])
def test_bridge_refuses_relay_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    leak_name: str,
) -> None:
    bridge = _load_bridge(monkeypatch)
    monkeypatch.setenv(leak_name, "must-not-enter-bridge")
    monkeypatch.setattr(
        bridge.web,
        "run_app",
        lambda *_args, **_kwargs: pytest.fail("bridge bound before checking credentials"),
    )

    with pytest.raises(SystemExit) as exc_info:
        bridge.main()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert leak_name in stderr
    assert "must-not-enter-bridge" not in stderr


def test_bridge_launcher_scrubs_relay_credentials() -> None:
    start_script = START_PATH.read_text(encoding="utf-8")
    launcher = start_script.split("start_atif_bridge() {", 1)[1].split(
        "\n}\n",
        1,
    )[0]

    assert "-u ATIF_RELAY_AUTH_TOKEN" in launcher
    assert "-u ATIF_RELAY_AUTHORIZATION" in launcher
    assert 'env "${scrub[@]}"' in launcher
