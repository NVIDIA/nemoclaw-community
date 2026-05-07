# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Microsoft Graph API credential sidecar.
#
# Accepts plain HTTP requests from bridges/skills on 127.0.0.1:8766,
# swaps `Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER_<SERVICE>` with the
# live access token for that service, and forwards to https://graph.microsoft.com
# via the upstream proxy (OpenShell L7 proxy chain).
#
# Multi-service support:
#   MS_GRAPH_SERVICES (env var, default "outlook") is a comma-separated list of
#   service names. For each name S, the sidecar expects:
#     {S.upper()}_SESSION_UUID  — UUID or OpenShell placeholder resolved by L7 proxy
#   Requests carry Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER_{S.upper()}.
#   The sidecar detects which service's placeholder is present and injects that
#   service's live token. Adding a new service requires only a build-arg change
#   and a UUID provider — no sidecar code changes.
#
# Why plain HTTP on the inbound leg:
#   HTTPS_PROXY causes Python HTTP clients to use CONNECT tunneling, which
#   encrypts the request before the proxy sees it. The sidecar must see the
#   Authorization header in plaintext to swap the placeholder. Keeping the
#   bridge-to-sidecar hop on loopback plain HTTP achieves this without any
#   TLS certificate management. The upstream leg (sidecar → Graph) is HTTPS.
#
# Bridge/skill configuration:
#   Set MS_GRAPH_SIDECAR_URL=http://127.0.0.1:8766 (or SIDECAR_LISTEN_PORT override).
#   The bridge replaces https://graph.microsoft.com/v1.0 with this URL.
#   NO_PROXY must include 127.0.0.1 so the client connects directly (not via
#   the OpenShell proxy) — this is already set in start.sh.

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="[ms-graph-sidecar] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_PLACEHOLDER_PREFIX = "MS_GRAPH_TOKEN_PLACEHOLDER_"
GRAPH_UPSTREAM_BASE = "https://graph.microsoft.com"

TOKEN_MANAGER_HOST = os.environ.get("TOKEN_MANAGER_HOST", "host.docker.internal")
TOKEN_MANAGER_PORT = int(os.environ.get("TOKEN_MANAGER_PORT", "8765"))

# Inside the sandbox the sidecar is loopback-only; in the test container we
# bind to 0.0.0.0 so the published port is reachable from the host.
LISTEN_HOST = os.environ.get("SIDECAR_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("SIDECAR_LISTEN_PORT", "8766"))
REFRESH_INTERVAL = 55 * 60  # seconds

# Headers that must not be forwarded between client and upstream
_HOP_BY_HOP = frozenset([
    "connection", "keep-alive", "proxy-connection",
    "transfer-encoding", "te", "trailer", "upgrade",
    "proxy-authorization", "proxy-authenticate",
    "host", "content-length",
])

# ── Per-service session state ─────────────────────────────────────────────────

@dataclass
class ServiceState:
    name: str
    uuid_value: str          # raw UUID or openshell:resolve:env:* placeholder;
                             # OpenShell L7 proxy resolves the placeholder before
                             # the request reaches the token manager
    live_token: str | None = None
    refresh_lock: asyncio.Lock | None = field(default=None, repr=False)


def _load_services() -> dict[str, ServiceState]:
    raw = os.environ.get("MS_GRAPH_SERVICES", "outlook")
    services: dict[str, ServiceState] = {}
    for name in (n.strip() for n in raw.split(",") if n.strip()):
        uuid_var = f"{name.upper()}_SESSION_UUID"
        uuid_val = os.environ.get(uuid_var)
        if not uuid_val:
            log.warning("Service %r configured but %s is not set — skipping", name, uuid_var)
            continue
        services[name] = ServiceState(name=name, uuid_value=uuid_val)
    return services


_services: dict[str, ServiceState] = _load_services()


# ── Token management ──────────────────────────────────────────────────────────

async def fetch_token(svc: ServiceState) -> str:
    # No explicit proxy: the sidecar's inherited HTTP_PROXY points directly to
    # the OpenShell L7 proxy, so OpenShell correctly attributes this connection
    # to /usr/local/bin/ms-graph-sidecar for policy enforcement.
    # (Routing through the decode-proxy would mis-attribute to python3.11.)
    #
    # Pass the session UUID in a header, not a query param.
    # OpenShell's plain-HTTP forward proxy resolves openshell:resolve:env:*
    # placeholders only in HTTP headers, not in URL query strings.
    token_url = f"http://{TOKEN_MANAGER_HOST}:{TOKEN_MANAGER_PORT}/token"
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(
            token_url,
            headers={"X-Session-Id": svc.uuid_value},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if "access_token" not in data:
                raise ValueError(f"Token manager returned no access_token: {data}")
            return data["access_token"]


async def refresh_token(svc: ServiceState, reason: str, stale_token: str | None = None) -> bool:
    if svc.refresh_lock is None:
        svc.refresh_lock = asyncio.Lock()
    async with svc.refresh_lock:
        if stale_token is not None and svc.live_token != stale_token:
            # Another coroutine already refreshed while we were waiting for the lock
            return True
        try:
            svc.live_token = await fetch_token(svc)
            log.info("Token refreshed for %r (%s, len=%d)", svc.name, reason, len(svc.live_token))
            return True
        except Exception as exc:
            log.error("Token refresh failed for %r (%s): %s", svc.name, reason, exc)
            return False


async def initial_token_loop(svc: ServiceState) -> None:
    """Keep retrying the initial token fetch for a service until it succeeds.

    Runs as a background task so the HTTP server binds immediately. Once the
    first token is in hand for this service, the task exits and the shared
    refresh_loop takes over.
    """
    attempt = 0
    while svc.live_token is None:
        attempt += 1
        if await refresh_token(svc, "initial acquisition"):
            log.info("Initial token acquired for %r after %d attempt(s)", svc.name, attempt)
            return
        wait = min(2 ** attempt, 15)
        log.warning(
            "Failed to fetch initial token for %r (attempt %d); retrying in %ds",
            svc.name, attempt, wait,
        )
        await asyncio.sleep(wait)


async def refresh_loop() -> None:
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        for svc in _services.values():
            log.info("Refreshing token for %r…", svc.name)
            ok = await refresh_token(svc, "scheduled refresh")
            if not ok:
                log.error("Continuing with existing token for %r after refresh failure", svc.name)


# ── Request forwarding ────────────────────────────────────────────────────────

async def handle(request: web.Request) -> web.StreamResponse:
    # Reconstruct the upstream URL: replace sidecar host with graph.microsoft.com
    upstream_url = GRAPH_UPSTREAM_BASE + str(request.rel_url)

    # Forward all non-hop-by-hop headers, fix Host
    base_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    base_headers["Host"] = "graph.microsoft.com"

    auth = base_headers.get("Authorization", "")

    # Detect which service's named placeholder is present
    matched_svc: ServiceState | None = None
    if _PLACEHOLDER_PREFIX in auth:
        for svc in _services.values():
            if f"{_PLACEHOLDER_PREFIX}{svc.name.upper()}" in auth:
                matched_svc = svc
                break

    uses_placeholder = matched_svc is not None
    body = await request.read()

    # auto_decompress=False: pass compressed bytes through as-is so the client
    # can decompress them itself. Without this, aiohttp decompresses the body
    # but the Content-Encoding header is still forwarded, confusing the client.
    async with aiohttp.ClientSession(auto_decompress=False, trust_env=True) as session:
        # Allow one reactive refresh+retry if Graph returns 401 on an
        # authenticated request. Non-placeholder requests are not retried.
        retry_after_refresh = uses_placeholder
        try:
            while True:
                fwd_headers = dict(base_headers)
                if uses_placeholder and matched_svc is not None:
                    placeholder = f"{_PLACEHOLDER_PREFIX}{matched_svc.name.upper()}"
                    if matched_svc.live_token:
                        fwd_headers["Authorization"] = auth.replace(
                            f"Bearer {placeholder}",
                            f"Bearer {matched_svc.live_token}",
                        )
                    else:
                        log.warning(
                            "Placeholder for %r in request but no live token yet; forwarding as-is",
                            matched_svc.name,
                        )

                async with session.request(
                    method=request.method,
                    url=upstream_url,
                    headers=fwd_headers,
                    data=body or None,
                    timeout=aiohttp.ClientTimeout(total=60),
                    allow_redirects=False,
                    ssl=True,
                ) as upstream:
                    resp_headers = {
                        k: v for k, v in upstream.headers.items()
                        if k.lower() not in _HOP_BY_HOP
                    }

                    if upstream.status == 401 and retry_after_refresh and matched_svc is not None:
                        error_body = await upstream.read()
                        log.warning("Graph returned 401 for %r; refreshing token and retrying once", matched_svc.name)
                        retry_after_refresh = False
                        stale = fwd_headers.get("Authorization", "").removeprefix("Bearer ")
                        if await refresh_token(matched_svc, "Graph 401 retry", stale_token=stale):
                            continue
                        # Refresh failed — return the original 401
                        return web.Response(
                            status=401,
                            headers=resp_headers,
                            body=error_body,
                        )

                    response = web.StreamResponse(
                        status=upstream.status,
                        headers=resp_headers,
                    )
                    await response.prepare(request)
                    async for chunk in upstream.content.iter_chunked(65536):
                        await response.write(chunk)
                    await response.write_eof()
                    return response
        except aiohttp.ClientError as exc:
            log.error("Upstream request failed: %s %s → %s", request.method, upstream_url, exc)
            return web.Response(status=502, text=f"Bad Gateway: {exc}")


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: web.Application) -> None:
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "(direct)"
    service_names = ", ".join(_services) or "(none)"
    log.info(
        "Starting token acquisition for services [%s] from %s:%d via %s (background)…",
        service_names, TOKEN_MANAGER_HOST, TOKEN_MANAGER_PORT, proxy,
    )
    loop = asyncio.get_event_loop()
    for svc in _services.values():
        loop.create_task(initial_token_loop(svc), name=f"token-init-{svc.name}")
    loop.create_task(refresh_loop(), name="token-refresh")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    app = web.Application()
    app.router.add_route("*", "/{path_info:.*}", handle)
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, LISTEN_HOST, LISTEN_PORT)
    await site.start()

    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "(direct)"
    service_names = ", ".join(_services) or "(none)"
    log.info(
        "Credential sidecar on %s:%d → %s | services: [%s] | proxy: %s",
        LISTEN_HOST, LISTEN_PORT, GRAPH_UPSTREAM_BASE, service_names, proxy,
    )

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
