#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Mock payment rail — HOST ONLY, the deliberately denied edge.

Binds 127.0.0.1 and is intentionally ABSENT from the sandbox's network
policy: the sandboxed agent has no route here, so a prompt can never turn
into a settlement (mirrors the payment-ops-hermes mock rail). Only the
host-side release gate calls it, and only after a GO verdict.

    POST /v1/settle   {claim, signature} -> {settled, tx}
    GET  /v1/ledger   everything settled so far (verification reads this)
    GET  /healthz

Settlements are appended to .run/rail-ledger.jsonl next to this file's
example dir so verify.sh can assert exactly what reached the rail.
"""

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIL_PORT = int(os.environ.get("RAIL_PORT", "8780"))
LEDGER_PATH = os.environ.get(
    "RAIL_LEDGER",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", ".run", "rail-ledger.jsonl"))

LEDGER = []


class Handler(BaseHTTPRequestHandler):
    server_version = "x402-mock-rail/1.0"

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "role": "mock-rail"})
        elif self.path == "/v1/ledger":
            self._json(200, {"settlements": LEDGER})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/settle":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return
        claim = payload.get("claim")
        signature = payload.get("signature")
        if not isinstance(claim, dict) or not signature:
            self._json(400, {"error": "claim and signature are required"})
            return
        entry = {"tx": "sim_" + uuid.uuid4().hex[:12], "claim": claim,
                 "signature": signature, "at": int(time.time())}
        LEDGER.append(entry)
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        sys.stdout.write("mock-rail: settled %s -> %s %s\n" % (
            entry["tx"], claim.get("amount"), claim.get("counterparty")))
        sys.stdout.flush()
        self._json(200, {"settled": True, "tx": entry["tx"]})

    def log_message(self, fmt, *args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", RAIL_PORT), Handler)
    sys.stdout.write("mock-rail: listening on 127.0.0.1:%d (HOST ONLY — "
                     "no sandbox route by design)\n" % RAIL_PORT)
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
