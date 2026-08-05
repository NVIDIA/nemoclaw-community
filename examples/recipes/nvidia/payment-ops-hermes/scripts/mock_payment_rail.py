#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock payment rail for the FinGuard demo — the host-side 'money mover'.

This stands in for an internal wire/ACH release endpoint (payments-rail.internal).
It runs on the HOST. The sandbox policy does NOT allow egress to the rail, so
the FinGuard agent cannot reach it. A human approver on the host can — that is
the maker-checker boundary the demo proves.

Endpoints:
  POST /release   header X-Approver: <name>   body {"payment_id","amount",...}
  GET  /released                              list of released payments

Run:  python3 scripts/mock_payment_rail.py --port 8780
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RELEASED: list[dict] = []


class RailHandler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/released":
            self._send(200, {"released": RELEASED, "count": len(RELEASED)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/release":
            self._send(404, {"error": "not found"})
            return
        approver = self.headers.get("X-Approver", "").strip()
        if not approver:
            # No human approver => no release. The checker must identify themselves.
            self._send(403, {"error": "release requires a human approver (X-Approver header)"})
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payment = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return
        record = {"payment_id": payment.get("payment_id"), "amount": payment.get("amount"),
                  "approver": approver, "status": "RELEASED"}
        RELEASED.append(record)
        self._send(200, {"status": "RELEASED", "released_by": approver, "payment": record})

    def log_message(self, *args) -> None:  # silence default logging
        return


def main() -> int:
    ap = argparse.ArgumentParser(description="Mock payment rail (host-side).")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 to expose via the Brev console")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RailHandler)
    print(f"Mock payment rail listening on http://{args.host}:{args.port} "
          f"(POST /release, GET /released)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
