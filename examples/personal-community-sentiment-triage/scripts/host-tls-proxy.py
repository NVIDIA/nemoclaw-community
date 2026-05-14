#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small HTTP reverse proxy for host-side TLS endpoints.

For use with local OpenShell gateways that cannot validate certificates issued
by the host's local CA (e.g. mkcert). The proxy listens on plain HTTP on the
host and forwards to any HTTPS upstream using the host trust store, so
containers reach local TLS services without needing the host CA installed.
"""

from __future__ import annotations

import argparse
import http.client
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream_host = "inference-api.nvidia.com"
    upstream_port = 443
    upstream_scheme = "https"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_OPTIONS(self) -> None:
        self._forward()

    def _forward(self) -> None:
        body = self._read_body()
        conn = self._connect()
        headers = self._forward_headers(len(body))
        path = self.path if self.path.startswith("/") else f"/{self.path}"

        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for key, value in resp.getheaders():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except BrokenPipeError:
            self.close_connection = True
        except Exception as exc:
            try:
                self.send_error(502, "Upstream inference proxy error")
            except BrokenPipeError:
                self.close_connection = True
            self.log_message("upstream request failed: %s", exc)
        finally:
            conn.close()
            self.close_connection = True

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        return self.rfile.read(int(length))

    def _forward_headers(self, body_len: int) -> dict[str, str]:
        # Lowercase keys: http.client doesn't dedup, and duplicate Content-Length
        # (case-mismatched inbound + proxy override) is an RFC 7230 §3.3.3
        # violation that nginx upstreams reject with 400.
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lk = key.lower()
            if lk not in HOP_BY_HOP_HEADERS:
                headers[lk] = value
        headers["host"] = self.upstream_host
        headers["content-length"] = str(body_len)
        headers["connection"] = "close"
        return headers

    def _connect(self) -> http.client.HTTPConnection:
        if self.upstream_scheme == "https":
            context = ssl.create_default_context()
            return http.client.HTTPSConnection(
                self.upstream_host,
                self.upstream_port,
                context=context,
                timeout=180,
            )
        return http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=180)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=18080, help="Listen port")
    parser.add_argument(
        "--upstream",
        required=True,
        help="Upstream HTTPS origin to proxy to (e.g. https://api.example.internal)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    upstream = urlparse(args.upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise SystemExit(f"Invalid upstream: {args.upstream}")
    ProxyHandler.upstream_scheme = upstream.scheme
    ProxyHandler.upstream_host = upstream.hostname
    ProxyHandler.upstream_port = upstream.port or (443 if upstream.scheme == "https" else 80)

    server = ThreadingHTTPServer((args.listen, args.port), ProxyHandler)
    print(
        f"Listening on http://{args.listen}:{args.port} -> "
        f"{ProxyHandler.upstream_scheme}://{ProxyHandler.upstream_host}:{ProxyHandler.upstream_port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
