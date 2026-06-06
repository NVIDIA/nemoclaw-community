#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Serve the finance UI and a mock Hermes-compatible API for local testing."""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"status": "ok", "service": "mock-hermes"})
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path.rstrip("/") == "/v1/chat/completions":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {}
            user_message = ""
            for message in payload.get("messages", []):
                if message.get("role") == "user":
                    user_message = str(message.get("content", ""))
            self._json(
                {
                    "id": "mock-finance-response",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": (
                                    "Mock analyst brief: focus on public price context, latest SEC facts, "
                                    "near-term catalysts, and explicit caveats. Request observed: "
                                    f"{user_message[:180]}"
                                ),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            return
        self.send_error(404)

    def _json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving finance UI and mock Hermes API at http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
