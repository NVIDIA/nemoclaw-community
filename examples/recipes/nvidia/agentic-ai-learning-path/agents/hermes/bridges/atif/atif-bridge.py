# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ATIF protocol-bridge sidecar.

Tiny HTTP→HTTPS forwarder that sits between nemo-relay-cli and OpenShell's
L7 proxy. nemo-relay's rustls (via object_store/reqwest) cannot validate the
L7 proxy's MITM cert because the cert lacks the `id-kp-serverAuth`
ExtendedKeyUsage extension (OpenShell
`crates/openshell-sandbox/src/l7/tls.rs:115-135` omits it) and rustls 0.23+
strictly rejects such certs. This bridge re-emits each request as HTTPS
using Python's `ssl` module (OpenSSL backend, via aiohttp), which accepts
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

Implementation note: uses aiohttp.web for the server side and
aiohttp.ClientSession for the outbound side. Both sides of the ATIF wire
(this bridge and extras/atif-export-relay/relay.py) share the same async
framework. The request body is buffered in memory and forwarded with an
explicit Content-Length; chunked Transfer-Encoding does not survive
OpenShell's L7 MITM proxy on PUTs (observed: outbound hangs until the
SDK times out ~30s in, with no traffic ever reaching the relay). At ATIF
blob sizes (~1MB per PUT, ~1 PUT/agent-turn) the buffer is cheap, and
matching the old bridge's wire shape is what keeps the proxy happy.

When the OpenShell EKU bug is fixed (one-line patch: add
`params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth]`),
this bridge becomes unnecessary and should be deleted.

Architecture: ../../../docs/atif-export.md.
"""

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import os
import ssl
import sys

import aiohttp
from aiohttp import web

log = logging.getLogger("atif-bridge")


# ── Config ─────────────────────────────────────────────────────────────────
UPSTREAM = os.environ.get(
    "ATIF_BRIDGE_UPSTREAM_URL", "https://host.openshell.internal:18443"
).rstrip("/")
BIND = os.environ.get("ATIF_BRIDGE_BIND_ADDR", "127.0.0.1:18444")

# Hop-by-hop headers must not be forwarded through a proxy (RFC 7230 §6.1).
# Host is dropped so aiohttp sets it from the outbound URL. Content-Length
# is dropped because aiohttp sets it from the streamed body automatically.
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


# ── Session lifecycle ──────────────────────────────────────────────────────
async def _init_session(app: web.Application) -> None:
    # Single ClientSession shared across requests so the HTTPS connection
    # pool to UPSTREAM is reused. aiohttp's default connector keeps up to
    # 100 connections; for the ATIF workload (~1 PUT/turn) one is enough,
    # but the default is fine and matches relay.py's posture.
    #
    # trust_env=True is load-bearing: OpenShell injects HTTPS_PROXY (pointing
    # at the L7 proxy on the namespace gateway) into the sandbox env, and
    # the bridge's outbound must go through that proxy — direct TCP connects
    # to the relay's resolved IP are black-holed by the sandbox network
    # namespace. aiohttp does NOT consult HTTPS_PROXY by default (httpx,
    # requests, curl all do); this flag is the explicit opt-in. Without it
    # session.request() hangs silently until the sock_connect timeout fires.
    # Reject any peer that can't do TLS 1.3 — modern peer set, fail loud on degradation.
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    app["session"] = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60.0, sock_connect=5.0),
        trust_env=True,
        connector=aiohttp.TCPConnector(ssl=ssl_ctx),
    )


async def _close_session(app: web.Application) -> None:
    session: aiohttp.ClientSession = app["session"]
    await session.close()


# ── Handlers ───────────────────────────────────────────────────────────────
async def healthz(_req: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def forward(request: web.Request) -> web.Response:
    session: aiohttp.ClientSession = request.app["session"]
    url = f"{UPSTREAM}{request.path_qs}"
    out_headers = forwardable_headers(request.headers)

    # Buffer the request body and forward with explicit Content-Length.
    # Passing `data=request.content` (a StreamReader) makes aiohttp's client
    # switch to Transfer-Encoding: chunked, which OpenShell's L7 MITM proxy
    # does not forward cleanly on PUTs — observed symptom: requests hang
    # until the in-sandbox SDK times out at ~30s, retry, and eventually
    # fail with no traffic ever reaching the relay. At ATIF blob sizes
    # (~1MB per PUT, ~1 PUT/agent-turn) the buffer is cheap; matching the
    # old bridge's Content-Length-based wire is what makes the proxy happy.
    body = await request.read()

    log.info(
        "forward method=%s path=%s bytes_up=%d",
        request.method, request.path, len(body),
    )

    try:
        async with session.request(
            request.method, url, headers=out_headers, data=body,
        ) as upstream:
            resp_body = await upstream.read()
            status = upstream.status
            resp_headers = forwardable_headers(upstream.headers)
    except aiohttp.ClientError as e:
        log.warning(
            "upstream_error type=%s msg=%s path=%s",
            type(e).__name__, e, request.path,
        )
        return web.Response(status=502, text=f"bridge upstream error: {e}")
    except Exception as e:  # noqa: BLE001 — log + 502 anything we didn't predict
        log.exception("upstream_unexpected path=%s", request.path)
        return web.Response(status=502, text=f"bridge unexpected error: {e}")

    log.info(
        "forwarded status=%d path=%s bytes_down=%d",
        status, request.path, len(resp_body),
    )
    return web.Response(status=status, body=resp_body, headers=resp_headers)


# ── App factory + entrypoint ───────────────────────────────────────────────
def make_app() -> web.Application:
    # client_max_size=0 disables aiohttp's request-body cap so the bridge
    # can forward arbitrary-sized PUTs. The real size cap is enforced by
    # the relay (relay.py sets 128MB via its own client_max_size).
    app = web.Application(client_max_size=0)
    app.router.add_get("/healthz", healthz)
    app.router.add_route("*", "/{tail:.*}", forward)
    app.on_startup.append(_init_session)
    app.on_cleanup.append(_close_session)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Defense-in-depth: refuse to start if any of the specific env vars
    # that would carry the ATIF bearer are present. The list is narrow on
    # purpose — see the _LEAK_NAMES definition above for why we don't
    # generalize to a suffix match. Runs BEFORE binding the port so a leak
    # fails fast without exposing a listener that should never have been
    # started.
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
    web.run_app(
        make_app(),
        host=host,
        port=int(port_str),
        print=lambda _msg: None,  # suppress aiohttp's startup banner; we log our own
        access_log=None,          # access logging happens inside `forward`
    )


if __name__ == "__main__":
    main()
