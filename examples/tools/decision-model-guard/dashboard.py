# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""DEMO ONLY: a local page that shows each guard decision next to its context.

The page reads the middleware's --demo-trace file and the mock service's
effects files, and refreshes every second. The trace contains full
conversation text. This page is a teaching aid. It is not a monitoring tool or
a security control.
"""

import argparse
import glob
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "dashboard.html"
MAX_EVENTS = 500


def read_jsonl(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-MAX_EVENTS:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # A writer may still be appending this line.
    return rows


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, trace, effects, **kwargs):
        self.trace, self.effects = trace, effects
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        pass

    def reply(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self.reply(PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/data":
            effects = []
            for pattern in self.effects:
                for name in sorted(glob.glob(pattern)):
                    effects += [dict(row, source=Path(name).name) for row in read_jsonl(name)]
            data = {"trace": read_jsonl(self.trace), "effects": effects}
            return self.reply(json.dumps(data).encode(), "application/json")
        return self.reply(b"Not found", "text/plain", 404)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--trace", required=True, help="JSONL from middleware.py --demo-trace")
    parser.add_argument(
        "--effects",
        action="append",
        default=[],
        help="Effects JSONL file or glob from workspace.py; repeat for more files",
    )
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(
        (args.listen, args.port), partial(Handler, trace=args.trace, effects=args.effects)
    )
    print(f"DEMO ONLY dashboard: http://{args.listen}:{args.port}/  (Ctrl-C stops it)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
