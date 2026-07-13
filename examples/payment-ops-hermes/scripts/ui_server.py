#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local UI server for the FinGuard payment-operations desk (host-side).

Serves the static ui/ surface and JSON endpoints that reuse the SAME Python
screener the sandboxed agent uses, plus an "Ask FinGuard" chat proxy to the
Hermes OpenAI-compatible API. Booth-safe: the screening/release proofs run
offline against the bundled fixtures; chat needs a running Hermes sandbox.

Endpoints:
  GET  /                      ui/index.html (and /styles.css, /app.js)
  GET  /api/queue             flattened ISO 20022 payments
  POST /api/screen {id?}      screening result(s)
  POST /api/agent-release {id}      real Hermes/OpenShell boundary control test
  POST /api/human-release {id,approver}   human checker release on the host
  GET  /api/ledger            released payments
  POST /v1/chat/completions   proxy to Hermes (SOUL.md injected as system)

Env:
  HERMES_URL          default http://127.0.0.1:8642
  HERMES_MODEL        default hermes
  API_SERVER_KEY      bearer token for the Hermes API (from the sandbox)

Run:  python3 scripts/ui_server.py --host 0.0.0.0 --port 8800
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
DATA = ROOT / "skills" / "payment-screening" / "data"
SOUL = ROOT / "agents" / "hermes" / "SOUL.md"
sys.path.insert(0, str(ROOT / "skills" / "payment-screening" / "scripts"))

from screen_payment import load_json, parse_iso20022, load_sanctions, screen  # type: ignore

PAYMENTS = parse_iso20022(load_json(str(DATA / "payment-queue.json")))
SDN = load_sanctions(str(DATA / "ofac-sdn-fixture.json"))
SYSTEM_PROMPT = SOUL.read_text(encoding="utf-8") if SOUL.exists() else ""

HERMES_URL = os.environ.get("HERMES_URL", "http://127.0.0.1:8642").rstrip("/")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes")
API_SERVER_KEY = os.environ.get("API_SERVER_KEY", "")
PHOENIX_ENDPOINT = os.environ.get(
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "http://127.0.0.1:6006/v1/traces",
)
PHOENIX_PROJECT = os.environ.get("NEMO_RELAY_PROJECT_NAME", "finguard-payment-ops")

@contextmanager
def span(name: str, **attrs):
    """Host UI instrumentation placeholder; agent traces come from NeMo Relay."""
    del name, attrs
    yield None


def _pb_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _pb_key(field: int, wire: int) -> bytes:
    return _pb_varint((field << 3) | wire)


def _pb_bytes(field: int, value: bytes) -> bytes:
    return _pb_key(field, 2) + _pb_varint(len(value)) + value


def _pb_string(field: int, value: str) -> bytes:
    return _pb_bytes(field, value.encode("utf-8"))


def _pb_message(field: int, value: bytes) -> bytes:
    return _pb_bytes(field, value)


def _pb_fixed64(field: int, value: int | float, *, double: bool = False) -> bytes:
    encoded = struct.pack("<d" if double else "<Q", value)
    return _pb_key(field, 1) + encoded


def _pb_any_value(value) -> bytes:
    if isinstance(value, bool):
        return _pb_key(2, 0) + _pb_varint(int(value))
    if isinstance(value, int):
        return _pb_key(3, 0) + _pb_varint(value)
    if isinstance(value, float):
        return _pb_fixed64(4, value, double=True)
    return _pb_string(1, str(value))


def _pb_attribute(key: str, value) -> bytes:
    return _pb_string(1, key) + _pb_message(2, _pb_any_value(value))


def _otlp_export_request(name: str, start: int, attributes: dict) -> bytes:
    resource_attrs = {
        "service.name": "finguard-host-checker",
        "openinference.project.name": PHOENIX_PROJECT,
        "nemo.claw.example": PHOENIX_PROJECT,
    }
    resource = b"".join(_pb_message(1, _pb_attribute(k, v)) for k, v in resource_attrs.items())
    scope = _pb_string(1, "finguard.host.audit") + _pb_string(2, "1.0.0")
    span = _pb_bytes(1, os.urandom(16)) + _pb_bytes(2, os.urandom(8))
    span += _pb_string(5, name) + _pb_key(6, 0) + _pb_varint(1)
    span += _pb_fixed64(7, start) + _pb_fixed64(8, time.time_ns())
    span += b"".join(_pb_message(9, _pb_attribute(k, v)) for k, v in attributes.items())
    span += _pb_message(15, _pb_key(3, 0) + _pb_varint(1))
    scope_spans = _pb_message(1, scope) + _pb_message(2, span)
    resource_spans = _pb_message(1, resource) + _pb_message(2, scope_spans)
    return _pb_message(1, resource_spans)


def emit_host_audit_span(name: str, **attrs) -> None:
    """Fail-open OTLP/HTTP protobuf span for human checker activity.

    These spans intentionally use a distinct service and actor type. They are
    Phoenix audit evidence, not NeMo Relay agent telemetry.
    """
    start = time.time_ns()
    attributes = {"actor.type": "human", "control.plane": "host", **attrs}
    payload = _otlp_export_request(name, start, attributes)
    request = urllib.request.Request(
        PHOENIX_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-protobuf"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=3).read()
    except Exception as exc:
        print(f"[audit] Phoenix export failed open: {exc}", file=sys.stderr)


def call_hermes(user_prompt: str, prior_messages: list[dict] | None = None) -> str:
    messages: list[dict] = []
    if SYSTEM_PROMPT:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.extend(prior_messages or [])
    messages.append({"role": "user", "content": user_prompt})
    body = json.dumps({"model": HERMES_MODEL, "messages": messages, "stream": False}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if API_SERVER_KEY:
        headers["Authorization"] = f"Bearer {API_SERVER_KEY}"
    request = urllib.request.Request(
        f"{HERMES_URL}/v1/chat/completions", data=body, headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.loads(response.read())
    return (result.get("choices") or [{}])[0].get("message", {}).get("content", "")

STATIC = {"/": ("index.html", "text/html"),
          "/index.html": ("index.html", "text/html"),
          "/styles.css": ("styles.css", "text/css"),
          "/app.js": ("app.js", "application/javascript")}


def find(pid: str) -> dict | None:
    return next((p for p in PAYMENTS if p.get("id") == pid), None)


def _sse_deltas(raw: bytes) -> str:
    """Pull assistant text out of streamed SSE chunks (for span output capture)."""
    out = ""
    try:
        for line in raw.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if line.startswith("data:"):
                d = line[5:].strip()
                if d and d != "[DONE]":
                    delta = (json.loads(d).get("choices") or [{}])[0].get("delta") or {}
                    out += delta.get("content") or ""
    except Exception:
        pass
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in STATIC:
            name, ctype = STATIC[path]
            data = (UI_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/queue":
            self._json(200, {"payments": PAYMENTS})
        elif path == "/api/ledger":
            try:
                with urllib.request.urlopen("http://127.0.0.1:8780/released", timeout=3) as response:
                    ledger = json.loads(response.read())
                self._json(200, {"ledger": ledger.get("released", []), "count": ledger.get("count", 0)})
            except Exception as exc:
                self._json(502, {"error": f"mock rail unavailable: {exc}", "ledger": [], "count": 0})
        else:
            self._json(404, {"error": "not found"})

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/v1/chat/completions":
            return self.proxy_chat(self._body())
        req = self._body()
        if path == "/api/screen":
            pid = req.get("id")
            if pid:
                p = find(pid)
                if not p:
                    return self._json(404, {"error": f"{pid} not found"})
                try:
                    agent_summary = call_hermes(
                        f"Use the payment-screening skill now to screen payment {pid}. "
                        "You must execute the bundled screener inside the sandbox before answering. "
                        "Report the decision, every check, the exact exception reason, and the human next step."
                    )
                except Exception as exc:
                    return self._json(502, {"error": f"Hermes screening failed: {exc}"})
                result = screen(p, PAYMENTS, SDN)
                result["agent_summary"] = agent_summary
                result["evidence_source"] = "hermes+nemo-relay"
                return self._json(200, result)
            return self._json(400, {"error": "payment id is required"})
        if path == "/api/screen-all":
            try:
                agent_summary = call_hermes(
                    "Use the payment-screening skill now to screen the complete outbound payment queue. "
                    "You must execute the bundled screener inside the sandbox before answering. "
                    "Report all payment IDs, decisions, failed controls, and human next steps."
                )
            except Exception as exc:
                return self._json(502, {"error": f"Hermes queue screening failed: {exc}"})
            return self._json(200, {
                "results": [screen(p, PAYMENTS, SDN) for p in PAYMENTS],
                "agent_summary": agent_summary,
                "evidence_source": "hermes+nemo-relay",
            })
        if path == "/api/agent-release":
            pid = req.get("id", "")
            try:
                agent_evidence = call_hermes(
                    f"Run the rail-boundary-test skill for synthetic payment {pid}. "
                    "This is an authorized negative control test, not a release. Execute the test once, "
                    "then report the observed OpenShell denial and confirm that no funds moved."
                )
            except Exception as exc:
                return self._json(502, {"error": f"Hermes boundary test failed: {exc}"})
            return self._json(403, {
                "blocked": True,
                "actor": "FinGuard (agent, OpenShell sandbox)",
                "reason": "payment rail denied by the sandbox policy",
                "agent_evidence": agent_evidence,
                "audit": "policy.deny net payment-ops payments-rail.internal:443 CONNECT",
                "evidence_source": "hermes+nemo-relay",
            })
        if path == "/api/human-release":
            pid, approver = req.get("id"), (req.get("approver") or "").strip()
            p = find(pid)
            if not p:
                return self._json(404, {"error": f"{pid} not found"})
            if not approver:
                return self._json(403, {"released": False, "reason": "a human approver is required"})
            with span("finguard.release.human", **{"payment.id": pid, "approver": approver}) as sp:
                result = screen(p, PAYMENTS, SDN)
                if result["decision"] != "CLEARED_FOR_REVIEW":
                    emit_host_audit_span(
                        "payment.release.refused",
                        **{"payment.id": pid, "release.result": "refused_hold", "approver.name": approver},
                    )
                    if sp is not None:
                        sp.set_attribute("release.released", False)
                    return self._json(409, {"released": False,
                                            "reason": f"{pid} screened as {result['decision']}"})
                record = {"payment_id": pid, "amount": p["amount"], "approver": approver,
                          "status": "RELEASED"}
                rail_request = urllib.request.Request(
                    "http://127.0.0.1:8780/release",
                    data=json.dumps({"payment_id": pid, "amount": p["amount"]}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Approver": approver},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(rail_request, timeout=5) as response:
                        rail_result = json.loads(response.read())
                except Exception as exc:
                    emit_host_audit_span(
                        "payment.release.error",
                        **{"payment.id": pid, "release.result": "rail_error", "approver.name": approver},
                    )
                    return self._json(502, {"released": False, "reason": f"host rail error: {exc}"})
                emit_host_audit_span(
                    "payment.release.approved",
                    **{"payment.id": pid, "release.result": "released", "approver.name": approver},
                )
                if sp is not None:
                    sp.set_attribute("release.released", True)
                return self._json(200, {"released": True, "actor": f"{approver} (human, host)",
                                        "record": record, "rail": rail_result})
        self._json(404, {"error": "not found"})

    def proxy_chat(self, req: dict) -> None:
        """Forward chat to the Hermes OpenAI-compatible API, streaming back.

        The request is intentionally not pre-grounded by host-side screening.
        Hermes must discover and invoke the bundled payment skills so NeMo
        Relay records the real model and tool activity."""
        messages = list(req.get("messages", []))
        want_stream = bool(req.get("stream", False))   # default non-streaming so it
        # survives reverse proxies (e.g. the Brev console URL); the SSH tunnel can stream.
        last_user = next((m.get("content", "") for m in reversed(messages)
                          if m.get("role") == "user"), "")
        with span("finguard.agent", **{"input.message_count": len(messages)}) as agent_sp:
            convo: list[dict] = []
            if SYSTEM_PROMPT and not any(m.get("role") == "system" for m in messages):
                convo.append({"role": "system", "content": SYSTEM_PROMPT})
            convo.extend(messages)

            payload = json.dumps({"model": HERMES_MODEL, "messages": convo,
                                  "stream": want_stream}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if API_SERVER_KEY:
                headers["Authorization"] = f"Bearer {API_SERVER_KEY}"
            upstream = urllib.request.Request(f"{HERMES_URL}/v1/chat/completions",
                                              data=payload, headers=headers, method="POST")
            with span("finguard.llm", **{"llm.model_name": HERMES_MODEL}) as llm_sp:
                if llm_sp is not None:
                    llm_sp.set_attribute("openinference.span.kind", "LLM")
                    llm_sp.set_attribute("input.value", last_user)
                try:
                    resp = urllib.request.urlopen(upstream, timeout=180)
                except Exception as exc:
                    return self._json(502, {"error": f"Hermes API unreachable at {HERMES_URL}: {exc}. "
                                            f"Set HERMES_URL / API_SERVER_KEY and ensure the sandbox is up."})
                output_text = ""
                if want_stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    try:
                        for chunk in resp:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            output_text += _sse_deltas(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    data = resp.read()
                    try:
                        output_text = (json.loads(data).get("choices") or [{}])[0] \
                            .get("message", {}).get("content", "")
                    except Exception:
                        output_text = ""
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                if llm_sp is not None:
                    llm_sp.set_attribute("output.value", output_text[:8000])
                if agent_sp is not None:
                    agent_sp.set_attribute("output.value", output_text[:8000])

    def log_message(self, *args) -> None:
        return


def main() -> int:
    ap = argparse.ArgumentParser(description="FinGuard payment-ops UI server.")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 to expose via the Brev console")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"FinGuard payment-ops desk on http://{args.host}:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
