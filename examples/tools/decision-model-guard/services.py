# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""External mock tools with independent effects, plus a real actor API proxy."""

import argparse
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scenario import SCENARIOS


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def actor_event(self, ok):
        path = self.server.effects.with_suffix(".actor.jsonl")
        with path.open("a") as stream:
            stream.write(json.dumps({"ok": ok}) + "\n")

    def respond(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.respond(200, {"status": "ok"})
        if self.path != self.server.scenario.read_path:
            return self.respond(404, {"error": "unknown_path"})
        content = self.server.scenario.context
        if self.server.attack:
            content += "\n" + self.server.scenario.injection
        return self.respond(
            200, {"tool_result": content, "action_fields": list(self.server.scenario.fields)}
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256 * 1024:
                return self.respond(413, {"error": "body_limit"})
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            return self.respond(400, {"error": "invalid_json"})
        if self.path == "/collector":
            with self.server.effects.with_suffix(".collector.jsonl").open("a") as stream:
                stream.write(json.dumps({"received": body}) + "\n")
            return self.respond(200, {"collected": True, "synthetic": True})
        if self.path == self.server.scenario.action_path:
            if not isinstance(body, dict) or set(body) != set(self.server.scenario.fields):
                return self.respond(400, {"error": "invalid_mail"})
            # Mock tools accept both authorized and prohibited actions.
            # Nothing sends real email, payments, or settings changes.
            event = {
                "action": body,
                "bad": self.server.scenario.is_bad(body),
                "committed_at_ns": time.time_ns(),
            }
            with self.server.effects.open("a") as stream:
                stream.write(json.dumps(event) + "\n")
            return self.respond(200, {"sent": True, "synthetic": True})
        if self.path != "/v1/chat/completions":
            return self.respond(404, {"error": "unknown_path"})
        # Credentials stay in this host process, outside the sandbox.
        body["model"] = self.server.actor_model
        body["stream"] = False
        headers = {"Content-Type": "application/json"}
        if self.server.actor_key:
            headers["Authorization"] = f"Bearer {self.server.actor_key}"
        request = urllib.request.Request(
            self.server.actor_url, data=json.dumps(body).encode(), headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                answer = json.loads(response.read(4 * 1024 * 1024))
            self.actor_event(True)
            return self.respond(200, answer)
        except Exception:
            self.actor_event(False)
            return self.respond(502, {"error": "actor_unavailable"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18580)
    parser.add_argument("--attack", action="store_true")
    parser.add_argument("--effects", default=".cache/effects.jsonl")
    parser.add_argument("--scenario", choices=SCENARIOS, default="recovery-code")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.listen, args.port), Handler)
    server.attack = args.attack
    server.scenario = SCENARIOS[args.scenario]
    server.effects = Path(args.effects)
    server.effects.parent.mkdir(parents=True, exist_ok=True)
    server.actor_url = os.environ.get("ACTOR_URL", "")
    server.actor_model = os.environ.get("ACTOR_MODEL", "")
    server.actor_key = os.environ.get("ACTOR_API_KEY", "")
    if not (server.actor_url and server.actor_model):
        parser.error("Set ACTOR_URL and ACTOR_MODEL")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
