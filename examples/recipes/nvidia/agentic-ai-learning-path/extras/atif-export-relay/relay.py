# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ATIF export relay.

Accepts completed trajectories from NeMo Relay's native HTTP ATIF storage,
validates the standard ``Authorization: Bearer <token>`` header, and forwards
each payload through a pluggable storage backend (S3, MinIO, or future
Azure/GCS/etc — see [backends/__init__.py](backends/__init__.py)).

NeMo Relay supplies the object identity in
``X-NeMo-Relay-ATIF-Filename``. The handler passes that bare key and the
relay-owned bucket to the backend. The S3 backend may scope the key under a
computed prefix (for example, the EC2 instance ID for an instance-scoped IAM
policy) via its pluggable prefixer. Real downstream credentials never enter
the sandbox.

Architecture: ../../docs/atif-export.md (or the plan file under .claude/plans/).
"""

from __future__ import annotations

import hmac
import logging
import os
import ssl
import sys
import unicodedata

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
# real bucket name; the relay writes every accepted trajectory to this
# configured bucket. The sandbox therefore cannot influence the target bucket.
RELAY_BUCKET = _required("ATIF_RELAY_BUCKET")

# Single bearer token issued at sandbox bring-up. `hmac.compare_digest` is
# used at check time for constant-time comparison.
ACCESS_TOKEN = _required("ATIF_RELAY_AUTH_TOKEN")


# ── Backend ────────────────────────────────────────────────────────────────
backend = build_backend(DOWNSTREAM)


# ── Handlers ───────────────────────────────────────────────────────────────
async def healthz(_req: web.Request) -> web.Response:
    return web.Response(text="ok\n")


def _is_safe_relative_key(filename: str) -> bool:
    """Accept Relay's path-safe relative names without normalizing them."""
    components = filename.split("/")
    return (
        bool(filename.strip())
        and "\\" not in filename
        and not filename.startswith("/")
        and all(component not in {"", ".", ".."} for component in components)
        and not any(unicodedata.category(char) == "Cc" for char in filename)
    )


async def relay(req: web.Request) -> web.StreamResponse:
    # aiohttp's header lookup is case-insensitive. Parse the authentication
    # scheme separately so only the raw token reaches compare_digest, and do
    # not log either the token or a prefix of it on rejection.
    authorization = req.headers.get("Authorization", "")
    auth_parts = authorization.split()
    if len(auth_parts) != 2 or auth_parts[0].casefold() != "bearer":
        log.info("reject reason=missing_bearer path=%s", req.path)
        return web.Response(status=403, text="missing or malformed bearer authorization")
    token = auth_parts[1]
    if not token:
        log.info("reject reason=missing_bearer path=%s", req.path)
        return web.Response(status=403, text="missing or malformed bearer authorization")
    if not hmac.compare_digest(token, ACCESS_TOKEN):
        log.info("reject reason=bad_token path=%s", req.path)
        return web.Response(status=403, text="bad bearer token")

    # NeMo Relay's native HTTP storage provides the same filename used by its
    # local and S3 destinations. The optional X-NeMo-Relay-ATIF-Session-ID is
    # accepted but is not needed for object identity. The backend alone owns
    # any dynamic or static prefix applied to this bare key.
    key = req.headers.get("X-NeMo-Relay-ATIF-Filename", "")
    if not _is_safe_relative_key(key):
        return web.Response(status=400, text="missing or invalid X-NeMo-Relay-ATIF-Filename")

    body = await req.read()
    content_type = req.headers.get("Content-Type")

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

    log.info(
        "forwarded status=204 bucket=%s key=%s etag=%s",
        RELAY_BUCKET, result.key or key, result.etag or "(missing)",
    )
    return web.Response(status=204)


# ── App factory + entrypoint ───────────────────────────────────────────────
def make_app() -> web.Application:
    app = web.Application(client_max_size=128 * 1024 * 1024)  # 128 MB ATIF cap
    app.router.add_get("/healthz", healthz, allow_head=False)
    app.router.add_post("/atif", relay)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info(
        "starting atif-export-relay backend=%s bind=%s bucket=%s transport=https",
        backend.label,
        BIND_ADDR,
        RELAY_BUCKET,
    )

    # Probe downstream credentials at startup so misconfiguration fails fast.
    try:
        log.info("downstream credentials acquired (%s)", backend.health_probe())
    except Exception as e:  # noqa: BLE001 — any creds-acquisition failure exits
        log.error("downstream credentials unavailable at startup: %s", e)
        sys.exit(1)

    # HTTPS listener. Native NeMo Relay sends the completed trajectory through
    # OpenShell's L7 proxy, which substitutes the bearer placeholder in transit.
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
