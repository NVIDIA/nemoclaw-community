# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""LLM-call accounting proxy.

Token cost is the second axis of this benchmark, so it cannot be self-reported:
a submission that undercounts its own ingest tokens would win on the axis the
benchmark exists to measure. Instead the runner points the system under test at
this proxy (``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL``) and counts what
actually crosses the wire.

The proxy is deliberately dumb — it forwards bytes and reads ``usage`` off the
response. It understands OpenAI-style (``prompt_tokens`` / ``completion_tokens``)
and Anthropic-style (``input_tokens`` / ``output_tokens``) payloads, streaming
or not. Systems that run a local model make no HTTP calls; their rows carry
``accounting: none-observed`` rather than a token count of zero.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Upstream failures are the difference between "this system is bad at the task"
# and "the endpoint was rate-limiting us"; without a record, a run that failed
# for the second reason looks exactly like one that failed for the first.
def _log_error(kind: str, detail: str) -> None:
    # Read the destination per call: the runner sets it after import.
    path = os.environ.get("MNEMO_PROXY_LOG", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{kind}\t{detail[:800]}\n")
    except OSError:
        pass


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


@dataclass
class Usage:
    """Running token totals, split by benchmark phase."""

    phase: str = "ingest"
    calls: dict[str, int] = field(default_factory=dict)
    input_tokens: dict[str, int] = field(default_factory=dict)
    output_tokens: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    by_phase_model: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, model: str, prompt: int, completion: int) -> None:
        with self.lock:
            self.calls[self.phase] = self.calls.get(self.phase, 0) + 1
            self.input_tokens[self.phase] = self.input_tokens.get(self.phase, 0) + prompt
            self.output_tokens[self.phase] = self.output_tokens.get(self.phase, 0) + completion
            if model:
                self.models[model] = self.models.get(model, 0) + 1
            bucket = self.by_phase_model.setdefault(self.phase, {}).setdefault(model or "unknown", [0, 0])
            bucket[0] += prompt
            bucket[1] += completion

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "calls": dict(self.calls),
                "input_tokens": dict(self.input_tokens),
                "output_tokens": dict(self.output_tokens),
                "models": dict(self.models),
                "by_phase_model": {
                    phase: {model: list(counts) for model, counts in models.items()}
                    for phase, models in self.by_phase_model.items()
                },
            }


def _extract_usage(payload: dict) -> tuple[str, int, int] | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    model = str(payload.get("model", ""))
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return model, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
    if "input_tokens" in usage or "output_tokens" in usage:
        return model, int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = ""
    usage = Usage()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - silence stdlib logging
        return

    def _control(self) -> bool:
        if not self.path.startswith("/__bench/"):
            return False
        if self.path.startswith("/__bench/phase/"):
            type(self).usage.phase = self.path.rsplit("/", 1)[-1]
            body = json.dumps({"phase": type(self).usage.phase}).encode()
        else:
            body = json.dumps(type(self).usage.snapshot()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self._control():
            return
        self._forward(b"")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if self._control():
            return
        length = int(self.headers.get("Content-Length") or 0)
        self._forward(self.rfile.read(length) if length else b"")

    def _forward(self, body: bytes) -> None:
        url = type(self).upstream.rstrip("/") + self.path
        _log_error("request", f"{self.command} {self.path} bytes={len(body)}")
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        request = urllib.request.Request(url, data=body or None, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(request, timeout=600)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            _log_error(f"http_{exc.code}", payload.decode("utf-8", "ignore"))
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        except Exception as exc:  # upstream unreachable — surface it to the caller
            _log_error("upstream_error", f"{type(exc).__name__}: {exc}")
            payload = json.dumps({"error": {"message": f"proxy upstream error: {exc}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in HOP_BY_HOP:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            for raw in response:
                self.wfile.write(raw)
                self.wfile.flush()
                line = raw.decode("utf-8", "ignore").strip()
                if line.startswith("data:") and '"usage"' in line:
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            found = _extract_usage(json.loads(chunk))
                        except json.JSONDecodeError:
                            found = None
                        if found:
                            type(self).usage.add(*found)
            return

        payload = response.read()
        try:
            body = json.loads(payload.decode("utf-8", "ignore"))
        except json.JSONDecodeError:
            body = None
        found = _extract_usage(body) if isinstance(body, dict) else None
        if found:
            type(self).usage.add(*found)
        # A 200 with no assistant text is how a shedding endpoint says no. It is
        # invisible in an error log, and downstream it looks like the model chose
        # to say nothing — so record it explicitly.
        if isinstance(body, dict) and body.get("choices"):
            choice = body["choices"][0] or {}
            message = choice.get("message") or {}
            if isinstance(message, dict) and not (message.get("content") or "").strip():
                _log_error(
                    "empty_content",
                    json.dumps({
                        "finish_reason": choice.get("finish_reason"),
                        "usage": body.get("usage"),
                        "model": body.get("model"),
                        "has_reasoning": bool(message.get("reasoning_content")),
                    }),
                )
        self.send_response(response.status)
        for key, value in response.headers.items():
            if key.lower() not in HOP_BY_HOP:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class AccountingProxy:
    """Context manager that runs the proxy on a free localhost port."""

    def __init__(self, upstream: str, port: int = 0) -> None:
        self.usage = Usage()
        handler = type("BoundHandler", (_Handler,), {"upstream": upstream, "usage": self.usage})
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def set_phase(self, phase: str) -> None:
        self.usage.phase = phase

    def __enter__(self) -> "AccountingProxy":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
