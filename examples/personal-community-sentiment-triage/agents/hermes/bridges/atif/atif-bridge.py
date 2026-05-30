"""ATIF protocol-bridge sidecar.

Tiny HTTP→HTTPS forwarder that sits between nemo-relay-cli and OpenShell's
L7 proxy. nemo-relay's rustls (via object_store/reqwest) cannot validate the
L7 proxy's MITM cert because the cert lacks the `id-kp-serverAuth`
ExtendedKeyUsage extension (OpenShell
`crates/openshell-sandbox/src/l7/tls.rs:115-135` omits it) and rustls 0.23+
strictly rejects such certs. This bridge re-emits each request as HTTPS
using Python's `ssl` module (OpenSSL backend, via httpx), which accepts
certs without serverAuth EKU — the same property that lets curl, requests,
git, and every other Hermes outbound work fine through the same L7 proxy
today.

The bridge is a pure protocol shim. It MUST NOT read ATIF_RELAY_AUTH_TOKEN
or any other credential. The bearer continues to ride as the placeholder
`openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN` in the request from
nemo-relay; the L7 proxy substitutes it during MITM after this bridge
forwards. That preserves the credential-opacity property of the original
design — real bearer never enters nemo-relay or bridge process memory; only
the L7 proxy ever sees the resolved value.

Implementation note: uses stdlib `http.server` because the sync threaded
server is more than adequate at the ATIF write rate (~1 PUT per agent
turn, ~1MB each), and `httpx` for outbound (the project's pinned HTTP
client, also used by `outlook-bridge.py`).

When the OpenShell EKU bug is fixed (one-line patch: add
`params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth]`),
this bridge becomes unnecessary and should be deleted.

Architecture: ../../../docs/atif-export.md.
"""

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import atexit
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

log = logging.getLogger("atif-bridge")


# ── Config ─────────────────────────────────────────────────────────────────
UPSTREAM = os.environ.get(
    "ATIF_BRIDGE_UPSTREAM_URL", "https://host.openshell.internal:18443"
).rstrip("/")
BIND = os.environ.get("ATIF_BRIDGE_BIND_ADDR", "127.0.0.1:18444")

# Hop-by-hop headers must not be forwarded through a proxy (RFC 7230 §6.1).
# Host is dropped so httpx sets it from the outbound URL. Content-Length
# is dropped because httpx sets it from the `content` kwarg automatically.
HOP_BY_HOP = frozenset(
    h.lower()
    for h in (
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    )
)

# Module-level client so the HTTPS connection pool to host.openshell.internal
# is reused across requests. httpx.Client is thread-safe.
_client = httpx.Client(timeout=60.0)
atexit.register(_client.close)

# Credential-leak guard — see main(). The set is narrow on purpose: it
# names the ONLY env vars that, if present in the bridge's env, mean the
# credential-opacity property (real ATIF bearer never enters bridge memory)
# has been broken. Other tokens visible in the sandbox env — SLACK_APP_TOKEN,
# GITHUB_TOKEN, MS_GRAPH_ACCESS_TOKEN, etc. — are for other in-sandbox
# services and don't flow through this bridge; we don't fail on them.
# start.sh's `env -u …` scrub is the primary defense; this check is the
# fail-loud trip-wire for the specific names that would carry the ATIF
# bearer if exported by mistake.
_LEAK_NAMES = frozenset({
    "ATIF_RELAY_AUTH_TOKEN",
    "AWS_SESSION_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
})


def forwardable_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


# ── Handler ────────────────────────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):
    # Quiet aiohttp-style access logging via our `log`, not stderr.
    def log_message(self, fmt, *args):
        log.info("access %s - %s", self.address_string(), fmt % args)

    def _send_simple(self, status: int, body: bytes, ctype: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_healthz(self):
        self._send_simple(200, b"ok\n")

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        url = f"{UPSTREAM}{self.path}"
        headers = forwardable_headers(self.headers)

        log.info(
            "forward method=%s path=%s bytes_up=%d",
            self.command,
            self.path,
            len(body),
        )

        try:
            resp = _client.request(self.command, url, headers=headers, content=body)
        except httpx.HTTPError as e:
            log.warning(
                "upstream_error type=%s msg=%s path=%s",
                type(e).__name__,
                e,
                self.path,
            )
            self._send_simple(502, f"bridge upstream error: {e}".encode())
            return

        log.info(
            "forwarded status=%d path=%s bytes_down=%d",
            resp.status_code,
            self.path,
            len(resp.content),
        )

        self.send_response(resp.status_code)
        for k, v in forwardable_headers(resp.headers).items():
            self.send_header(k, v)
        # Set Content-Length from the buffered body — HOP_BY_HOP stripped
        # the upstream's Content-Length so we have to re-emit it ourselves.
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        self.wfile.write(resp.content)

    def _dispatch(self):
        if self.path == "/healthz" and self.command == "GET":
            self._serve_healthz()
            return
        self._forward()

    # S3 PutObject is the primary path; the rest are defensive coverage in
    # case object_store ever issues a HEAD/GET/etc. against this endpoint.
    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_OPTIONS(self):
        self._dispatch()


# ── Entrypoint ─────────────────────────────────────────────────────────────
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Defense-in-depth: refuse to start if any of the specific env vars
    # that would carry the ATIF bearer are present. The list is narrow on
    # purpose — see the _LEAK_NAMES definition above for why we don't
    # generalize to a suffix match.
    leaks = sorted(name for name in _LEAK_NAMES if name in os.environ)
    if leaks:
        sys.stderr.write(
            f"atif-bridge: refusing to start — credential env var(s) present: {', '.join(leaks)}\n"
        )
        sys.exit(2)

    host, _, port_str = BIND.partition(":")
    log.info(
        "starting atif-bridge bind=%s upstream=%s mode=http→https-protocol-shim",
        BIND,
        UPSTREAM,
    )
    server = ThreadingHTTPServer((host, int(port_str)), BridgeHandler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
