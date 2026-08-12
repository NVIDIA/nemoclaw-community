# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ATIF export relay.

Accepts S3-shaped requests from sandboxes, validates a bearer token in a
configurable header (default `X-Amz-Security-Token`), and forwards via a
pluggable storage backend (S3, MinIO, or future Azure/GCS/etc — see
[backends/__init__.py](backends/__init__.py)).

The handler is key-agnostic: it forwards `(bucket, key)` to the backend as-is.
The S3 backend may *scope* the key under a computed prefix (e.g. the EC2
instance-id, for an instance-scoped bucket IAM policy) via its pluggable
prefixer — see [backends/prefixers.py](backends/prefixers.py). That is a
backend concern; this handler does not touch keys.

**Why we don't validate the SigV4 signature**: doing so would require the
relay to share the AWS secret access key with whatever signs the request.
In our flow the signer is the SDK inside the sandbox, which means the
secret would have to live in sandbox process memory — defeating the
credential-opacity property the whole architecture is built on (the L7
proxy substitutes a bearer placeholder at egress, so the real bearer
never lands in nemo-relay). The L7 proxy can't sign on the SDK's behalf
either (it only does whole-value header substitution). So SigV4 cannot
be validated here without sacrificing what makes the design safe.

The wire still *looks* like SigV4 because nemo-relay-cli's `object_store`
backend speaks S3, which insists on building an `AWS4-HMAC-SHA256`
Authorization envelope. The envelope is built with the literal junk AKID
from `AWS_ACCESS_KEY_ID` and a meaningless signature; the relay ignores
it. The actual auth is the bearer in `X-Amz-Security-Token` (or whatever
`ATIF_RELAY_AUTH_HEADER` points at). Real downstream credentials never
enter the sandbox.

Architecture: ../../docs/atif-export.md (or the plan file under .claude/plans/).
"""

from __future__ import annotations

import hmac
import logging
import os
import ssl
import sys
from urllib.parse import unquote

from aiohttp import web

from backends import (
    BackendError,
    BackendTransportError,
    build_backend,
)

log = logging.getLogger("atif-export-relay")


# ── Config ─────────────────────────────────────────────────────────────────
def _required(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        sys.stderr.write(f"required env var unset: {key}\n")
        sys.exit(2)
    return v


DOWNSTREAM = _required("ATIF_RELAY_DOWNSTREAM")
BIND_ADDR = os.environ.get("ATIF_RELAY_BIND_ADDR", "0.0.0.0:18443")
# The relay is the sole owner of the downstream bucket. The sandbox bakes no
# real bucket name — it sends a vestigial placeholder in the request path (like
# the junk SigV4 creds) — and the relay writes every object to THIS configured
# bucket. The sandbox therefore cannot influence the target bucket at all,
# which is strictly stronger than the old request-bucket allowlist.
RELAY_BUCKET = _required("ATIF_RELAY_BUCKET")

# Single bearer token issued at sandbox bring-up. `hmac.compare_digest` is
# used at check time for constant-time comparison.
ACCESS_TOKEN = _required("ATIF_RELAY_AUTH_TOKEN")

# Which HTTP header carries the bearer. Default matches today's S3-SDK
# client (which emits `X-Amz-Security-Token`). Operators can flip this to
# `Authorization` (or anything else) without a code change if/when a
# non-S3-SDK client wires in.
AUTH_HEADER = os.environ.get("ATIF_RELAY_AUTH_HEADER", "X-Amz-Security-Token")


# ── Backend ────────────────────────────────────────────────────────────────
backend = build_backend(DOWNSTREAM)


# ── Handlers ───────────────────────────────────────────────────────────────
async def healthz(_req: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def relay(req: web.Request) -> web.StreamResponse:
    # Method check first — short-circuits before buffering the body so a
    # non-PUT can't make the relay allocate 128MB just to be rejected.
    if req.method != "PUT":
        log.info("reject reason=method_not_supported method=%s path=%s", req.method, req.path)
        return web.Response(status=405, text="only PUT supported")

    # Bearer validation. The header value rides as-is; the L7 proxy has
    # already substituted the placeholder before this point.
    token = req.headers.get(AUTH_HEADER, "").strip()
    if not token:
        log.info("reject reason=missing_bearer path=%s", req.path)
        return web.Response(status=403, text=f"missing {AUTH_HEADER}")
    if not hmac.compare_digest(token, ACCESS_TOKEN):
        log.info("reject reason=bad_token token_prefix=%s... path=%s", token[:8], req.path)
        return web.Response(status=403, text="bad bearer token")

    # Path-style only: `/bucket/key`. Virtual-hosted addressing is never
    # used in our flow (the atif-bridge pins Host to host.openshell.internal).
    # The leading path segment is a VESTIGIAL placeholder (the sandbox bakes no
    # real bucket name); parse it only to split off the object key, then ignore
    # it — the relay always writes to RELAY_BUCKET. The backend owns the key
    # prefix, so the key here is the bare key from the sandbox.
    req_bucket, _, rest = req.path.lstrip("/").partition("/")
    key = unquote(rest)
    if not key:
        return web.Response(status=400, text="empty object key")

    body = await req.read()
    content_type = req.headers.get("Content-Type")
    if req_bucket and req_bucket != RELAY_BUCKET:
        log.debug("ignoring vestigial request bucket=%s (relay writes to %s)", req_bucket, RELAY_BUCKET)

    # backend.put_object applies the relay-owned key prefix and logs the
    # effective key (see S3CompatibleBackend); no pre-prefix log here.
    try:
        result = await backend.put_object(RELAY_BUCKET, key, body, content_type)
    except BackendError as e:
        log.warning("downstream_error code=%s status=%d msg=%s", e.code, e.status, e.message)
        return web.Response(status=e.status, text=str(e))
    except BackendTransportError as e:
        log.warning("downstream_transport_error msg=%s", e)
        return web.Response(status=502, text=f"downstream unreachable: {e}")

    # ETag forwarding is load-bearing: nemo-relay's object_store 0.13 requires
    # an ETag in the response to consider the PUT successful. A missing ETag
    # gets recorded as `Error::MissingEtag` in the dispatcher's sink_errors,
    # which then permanently filters that sink out for the rest of the
    # process lifetime. See backends/base.py:PutResult.
    response_headers = {"ETag": result.etag} if result.etag else {}
    log.info(
        "forwarded status=200 bucket=%s key=%s etag=%s",
        RELAY_BUCKET, result.key or key, result.etag or "(missing)",
    )
    return web.Response(status=200, text="", headers=response_headers)


# ── App factory + entrypoint ───────────────────────────────────────────────
def make_app() -> web.Application:
    app = web.Application(client_max_size=128 * 1024 * 1024)  # 128 MB ATIF cap
    app.router.add_get("/healthz", healthz)
    app.router.add_route("*", "/{tail:.*}", relay)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info(
        "starting atif-export-relay backend=%s bind=%s bucket=%s auth_header=%s transport=https",
        backend.label,
        BIND_ADDR,
        RELAY_BUCKET,
        AUTH_HEADER,
    )

    # Probe downstream credentials at startup so misconfiguration fails fast.
    try:
        log.info("downstream credentials acquired (%s)", backend.health_probe())
    except Exception as e:  # noqa: BLE001 — any creds-acquisition failure exits
        log.error("downstream credentials unavailable at startup: %s", e)
        sys.exit(1)

    # HTTPS listener. The sandbox→relay wire is encrypted end-to-end: the
    # in-sandbox atif-bridge sidecar (Python ssl, OpenSSL backend) forwards
    # over HTTPS through OpenShell's L7 proxy, which MITMs and substitutes
    # the bearer placeholder during transit. See docs/atif-export.md
    # "Sandbox→relay TLS via Python protocol-bridge sidecar" for the wire
    # diagram and the OpenShell EKU bug that makes the bridge necessary.
    # Downstream (relay → S3/MinIO) is also TLS via boto3.
    tls_cert = _required("ATIF_RELAY_TLS_CERT")
    tls_key = _required("ATIF_RELAY_TLS_KEY")
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    # Reject any peer that can't do TLS 1.3 — modern peer set, fail loud on degradation.
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ssl_ctx.load_cert_chain(tls_cert, tls_key)

    host, _, port_str = BIND_ADDR.partition(":")
    web.run_app(
        make_app(),
        host=host,
        port=int(port_str),
        ssl_context=ssl_ctx,
        print=lambda _msg: None,  # use our own startup log line instead of aiohttp's banner
    )


if __name__ == "__main__":
    main()
