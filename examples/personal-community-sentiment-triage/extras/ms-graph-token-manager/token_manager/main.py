# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# MS Graph token manager — UUID session architecture.
#
# External API (port TOKEN_MANAGER_PORT, default 8765):
#   POST /auth/start             — initiate auth flow; returns session_id (UUID4)
#   GET  /auth/poll?session_id=X — poll for completion
#   GET  /token                  — retrieve live access token (X-Session-Id header,
#                                  or ?session_id= query param for curl testing)
#   GET  /health                 — service health + session list (no session_ids)
#
# OAuth callback server (port OAUTH_REDIRECT_PORT, default 51247):
#   GET  /                       — receives ?code=...&state=... after browser auth
#
# Session lifecycle:
#   /auth/start  → PendingFlow in _pending[session_id]
#   callback/poll → _promote_to_session → AppState in _sessions[session_id]
#   /token       → looks up _sessions[session_id]

import asyncio
import base64
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import msal
from aiohttp import web
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logging.basicConfig(
    level=logging.INFO,
    format="[token-manager] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

CACHE_FILE = os.environ.get("TOKEN_CACHE_FILE", "/token-cache/msal_cache.bin")
CACHE_PASSPHRASE = os.environ.get("TOKEN_CACHE_PASSPHRASE")
HTTP_PORT = int(os.environ.get("TOKEN_MANAGER_PORT", "8765"))
OAUTH_REDIRECT_PORT = int(os.environ.get("OAUTH_REDIRECT_PORT", "51247"))
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_REDIRECT_PORT}"
REFRESH_BUFFER_SECONDS = 600  # refresh 10 min before expiry
PENDING_CLEANUP_INTERVAL = 60  # seconds between expired-flow cleanup runs
COMPLETED_TTL = 300  # seconds to keep _completed entries after browser callback

# Session config is persisted alongside the MSAL cache so sessions survive
# token manager restarts without re-auth. Credentials (client_id, tenant_id,
# login_hint) are written here when a session is first authenticated.
SESSION_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(CACHE_FILE)), "sessions.json")

# Used for the initial interactive auth flow. Empty avoids explicit consent
# prompts in corporate tenants where Mail scopes are admin-pre-consented on
# the app registration — Microsoft returns the pre-consented scopes anyway.
SCOPES = []

# Used only for acquire_token_silent (token refresh). ".default" asks Microsoft
# for all pre-consented permissions on the app registration without triggering
# a new consent prompt. Required so the refresh grant succeeds after the
# access token expires (empty scope list causes the refresh grant to fail).
REFRESH_SCOPES = ["https://graph.microsoft.com/.default"]

# ── Token cache (optionally encrypted at rest) ────────────────────────────────

_SALT = os.environ.get("TOKEN_CACHE_SALT", "nemoclaw-ms-graph-v1").encode()


def _fernet(passphrase: str) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=480_000)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return Fernet(key)


def load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if not os.path.exists(CACHE_FILE):
        log.info("No token cache found at %s — starting fresh", CACHE_FILE)
        return cache
    with open(CACHE_FILE, "rb") as f:
        raw = f.read()
    if CACHE_PASSPHRASE:
        raw = _fernet(CACHE_PASSPHRASE).decrypt(raw)
        log.info("Loaded encrypted token cache from %s", CACHE_FILE)
    else:
        log.info("Loaded plaintext token cache from %s", CACHE_FILE)
    cache.deserialize(raw.decode())
    return cache


def save_cache(cache: msal.SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    os.makedirs(os.path.dirname(os.path.abspath(CACHE_FILE)), exist_ok=True)
    data = cache.serialize().encode()
    if CACHE_PASSPHRASE:
        data = _fernet(CACHE_PASSPHRASE).encrypt(data)
    with open(CACHE_FILE, "wb") as f:
        f.write(data)
    log.info("Saved %s token cache to %s", "encrypted" if CACHE_PASSPHRASE else "plaintext", CACHE_FILE)


# ── Session config persistence ────────────────────────────────────────────────

def _load_session_configs() -> list[dict]:
    try:
        with open(SESSION_CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_session_configs() -> None:
    configs = [
        {
            "session_id": state.session_id,
            "client_id": state.client_id,
            "tenant_id": state.tenant_id,
            "login_hint": state.username,
        }
        for state in _sessions.values()
    ]
    try:
        os.makedirs(os.path.dirname(SESSION_CONFIG_FILE), exist_ok=True)
        with open(SESSION_CONFIG_FILE, "w") as f:
            json.dump(configs, f, indent=2)
    except OSError:
        log.warning("Could not persist session config to %s", SESSION_CONFIG_FILE)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PendingFlow:
    """In-flight auth flow — not yet authenticated."""
    session_id: str                # UUID4 — same ID that becomes the permanent session key
    client_id: str
    tenant_id: str
    client_secret: str | None
    app: msal.PublicClientApplication
    cache: msal.SerializableTokenCache
    flow_type: str                 # "device" | "browser"
    device_flow: dict | None = None
    auth_code_flow: dict | None = None
    flow_expires_at: float = 0.0   # Unix timestamp for device code expiry


@dataclass
class AppState:
    """Authenticated session — confirmed, has live token and background refresh."""
    session_id: str                # UUID4 — matches the key in _sessions
    client_id: str
    tenant_id: str
    username: str                  # discovered post-auth from MSAL account object
    client_secret: str | None
    app: msal.PublicClientApplication
    cache: msal.SerializableTokenCache
    access_token: str | None = None
    expires_at: datetime | None = None
    refresh_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def authenticated(self) -> bool:
        return self.access_token is not None and (
            self.expires_at is None or self.expires_at > datetime.now(timezone.utc)
        )

    @property
    def expires_at_iso(self) -> str | None:
        return self.expires_at.isoformat() if self.expires_at else None


# Registries
_sessions: dict[str, AppState] = {}      # session_id → AppState (authenticated)
_pending: dict[str, PendingFlow] = {}    # session_id → PendingFlow (in-flight)
_completed: dict[str, str] = {}          # session_id → username (browser callback bridge)
_completed_at: dict[str, float] = {}     # session_id → Unix timestamp (for TTL cleanup)
_cache: msal.SerializableTokenCache | None = None


def _build_msal_app(
    client_id: str,
    tenant_id: str,
    client_secret: str | None,
    cache: msal.SerializableTokenCache,
) -> msal.PublicClientApplication | msal.ConfidentialClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    if client_secret:
        return msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=client_secret, token_cache=cache
        )
    return msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)


def _promote_to_session(pending: PendingFlow, username: str, result: dict) -> AppState:
    """Move a completed PendingFlow into _sessions as an authenticated AppState."""
    state = AppState(
        session_id=pending.session_id,
        client_id=pending.client_id,
        tenant_id=pending.tenant_id,
        username=username,
        client_secret=pending.client_secret,
        app=pending.app,
        cache=pending.cache,
    )
    _apply_token(state, result)
    save_cache(state.cache)
    _sessions[pending.session_id] = state
    _pending.pop(pending.session_id, None)
    _save_session_configs()
    state.refresh_task = asyncio.get_event_loop().create_task(
        _refresh_loop(state), name=f"refresh-{pending.session_id[:8]}"
    )
    log.info(
        "Session promoted: session_id=%s username=%s expires=%s",
        pending.session_id, username, state.expires_at_iso,
    )
    return state


def _try_silent(state: AppState) -> bool:
    accounts = state.app.get_accounts(username=state.username)
    if not accounts:
        return False
    result = state.app.acquire_token_silent(REFRESH_SCOPES, account=accounts[0])
    if result and "access_token" in result:
        _apply_token(state, result)
        save_cache(state.cache)
        return True
    log.warning(
        "Silent token acquisition failed for %s: %s",
        state.username,
        result.get("error_description") if result else "no cached token",
    )
    return False


def _apply_token(state: AppState, result: dict) -> None:
    state.access_token = result["access_token"]
    expires_in = int(result.get("expires_in", 3600))
    state.expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc)


async def _refresh_loop(state: AppState) -> None:
    while True:
        if state.authenticated and state.expires_at:
            secs_until_expiry = (state.expires_at - datetime.now(timezone.utc)).total_seconds()
            sleep_secs = max(60, secs_until_expiry - REFRESH_BUFFER_SECONDS)
            log.info(
                "Session %s (%s): valid for %.0fs, refreshing in %.0fs",
                state.session_id[:8], state.username, secs_until_expiry, sleep_secs,
            )
            await asyncio.sleep(sleep_secs)
        else:
            await asyncio.sleep(30)

        log.info("Session %s (%s): refreshing token…", state.session_id[:8], state.username)
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, _try_silent, state)
        if not ok:
            log.warning(
                "Session %s (%s): silent refresh failed — token will expire",
                state.session_id[:8], state.username,
            )


async def _cleanup_pending() -> None:
    """Remove expired pending flows and stale _completed entries."""
    while True:
        await asyncio.sleep(PENDING_CLEANUP_INTERVAL)
        now = time.time()

        expired = [
            sid for sid, p in _pending.items()
            if p.flow_type == "device" and p.flow_expires_at > 0 and now > p.flow_expires_at
        ]
        for sid in expired:
            log.info("Cleanup: expired device flow session_id=%s", sid[:8])
            _pending.pop(sid, None)

        stale = [sid for sid, ts in _completed_at.items() if now - ts > COMPLETED_TTL]
        for sid in stale:
            _completed.pop(sid, None)
            _completed_at.pop(sid, None)


# ── HTTP handlers ─────────────────────────────────────────────────────────────

async def handle_auth_start(request: web.Request) -> web.Response:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    client_id = body.get("client_id")
    tenant_id = body.get("tenant_id")
    client_secret = body.get("client_secret")
    scopes = body.get("scopes", SCOPES)
    auth_type = body.get("type", "browser")
    login_hint = body.get("login_hint", "")

    if not client_id or not tenant_id:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"error": "missing_params",
                             "message": "client_id and tenant_id are required"}),
        )

    # Deduplication: return existing session if login_hint matches an authenticated session.
    if login_hint:
        for state in _sessions.values():
            if (
                state.client_id == client_id
                and state.tenant_id == tenant_id
                and state.username.lower() == login_hint.lower()
                and state.authenticated
            ):
                log.info(
                    "Auth start: reusing existing session for %s (session_id=%s)",
                    login_hint, state.session_id[:8],
                )
                return web.Response(
                    status=200,
                    content_type="application/json",
                    text=json.dumps({
                        "session_id": state.session_id,
                        "status": "already_authenticated",
                        "username": state.username,
                        "expires_at": state.expires_at_iso,
                    }),
                )

    session_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    app = _build_msal_app(client_id, tenant_id, client_secret, _cache)

    if auth_type == "browser":
        flow = await loop.run_in_executor(
            None,
            lambda: app.initiate_auth_code_flow(
                scopes=scopes,
                redirect_uri=OAUTH_REDIRECT_URI,
                **({"login_hint": login_hint} if login_hint else {}),
            ),
        )
        if "auth_uri" not in flow:
            return web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"error": "browser_flow_failed",
                                 "message": flow.get("error_description", "unknown")}),
            )
        _pending[session_id] = PendingFlow(
            session_id=session_id,
            client_id=client_id,
            tenant_id=tenant_id,
            client_secret=client_secret,
            app=app,
            cache=_cache,
            flow_type="browser",
            auth_code_flow=flow,
        )
        log.info("Browser flow started: session_id=%s client_id=%s", session_id[:8], client_id)
        return web.Response(
            status=200,
            content_type="application/json",
            text=json.dumps({
                "session_id": session_id,
                "type": "browser",
                "auth_uri": flow["auth_uri"],
            }),
        )

    # Device code flow
    flow = await loop.run_in_executor(
        None, lambda: app.initiate_device_flow(scopes=scopes)
    )
    if "user_code" not in flow:
        return web.Response(
            status=500,
            content_type="application/json",
            text=json.dumps({"error": "device_flow_failed",
                             "message": flow.get("error_description", "unknown")}),
        )

    _pending[session_id] = PendingFlow(
        session_id=session_id,
        client_id=client_id,
        tenant_id=tenant_id,
        client_secret=client_secret,
        app=app,
        cache=_cache,
        flow_type="device",
        device_flow=flow,
        flow_expires_at=time.time() + flow.get("expires_in", 900),
    )
    log.info(
        "Device flow started: session_id=%s client_id=%s user_code=%s",
        session_id[:8], client_id, flow["user_code"],
    )
    return web.Response(
        status=200,
        content_type="application/json",
        text=json.dumps({
            "session_id": session_id,
            "type": "device",
            "url": "https://microsoft.com/devicelogin",
            "user_code": flow["user_code"],
            "expires_in": flow.get("expires_in", 900),
        }),
    )


async def handle_auth_poll(request: web.Request) -> web.Response:
    session_id = request.rel_url.query.get("session_id")
    if not session_id:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"error": "missing_params", "message": "session_id is required"}),
        )

    if session_id in _sessions:
        state = _sessions[session_id]
        return web.Response(
            status=200,
            content_type="application/json",
            text=json.dumps({
                "status": "complete",
                "session_id": session_id,
                "username": state.username,
                "expires_at": state.expires_at_iso,
            }),
        )

    if session_id not in _pending:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"status": "error",
                             "message": "No auth flow found for this session_id"}),
        )

    pending = _pending[session_id]

    if pending.flow_type == "browser":
        # Check if callback completed and session was promoted
        if session_id in _completed and session_id in _sessions:
            state = _sessions[session_id]
            return web.Response(
                status=200,
                content_type="application/json",
                text=json.dumps({
                    "status": "complete",
                    "session_id": session_id,
                    "username": state.username,
                    "expires_at": state.expires_at_iso,
                }),
            )
        return web.Response(
            status=202,
            content_type="application/json",
            text=json.dumps({"status": "pending", "type": "browser"}),
        )

    # Device code flow
    if time.time() > pending.flow_expires_at:
        _pending.pop(session_id, None)
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"status": "expired",
                             "message": "Device code expired — call /auth/start again"}),
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: pending.app.acquire_token_by_device_flow(
            pending.device_flow, exit_condition=lambda flow: True
        ),
    )

    if result and "access_token" in result:
        accounts = pending.app.get_accounts()
        username = accounts[0].get("username", "") if accounts else ""
        _promote_to_session(pending, username, result)
        log.info("Device flow completed: session_id=%s username=%s", session_id[:8], username)
        return web.Response(
            status=200,
            content_type="application/json",
            text=json.dumps({
                "status": "complete",
                "session_id": session_id,
                "username": username,
                "expires_at": _sessions[session_id].expires_at_iso,
            }),
        )

    return web.Response(
        status=202,
        content_type="application/json",
        text=json.dumps({"status": "pending"}),
    )


async def handle_token(request: web.Request) -> web.Response:
    # Accept session_id from X-Session-Id header (preferred: OpenShell resolves the
    # openshell:resolve:env:* placeholder there) or query param (direct / curl use).
    session_id = request.headers.get("X-Session-Id") or request.rel_url.query.get("session_id")
    if not session_id:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"error": "missing_params", "message": "session_id is required"}),
        )

    state = _sessions.get(session_id)
    if state is None:
        return web.Response(
            status=401,
            content_type="application/json",
            text=json.dumps({
                "error": "not_authenticated",
                "message": "Unknown session_id — call POST /auth/start to initiate auth flow",
            }),
        )

    if not state.authenticated:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _try_silent, state)

    if not state.authenticated:
        return web.Response(
            status=401,
            content_type="application/json",
            text=json.dumps({
                "error": "token_expired",
                "message": "Token expired and silent refresh failed — call POST /auth/start",
            }),
        )

    expires_in = max(0, int(
        (state.expires_at - datetime.now(timezone.utc)).total_seconds()
    )) if state.expires_at else 0

    return web.Response(
        status=200,
        content_type="application/json",
        text=json.dumps({
            "access_token": state.access_token,
            "expires_at": state.expires_at_iso,
            "expires_in": expires_in,
        }),
    )


async def handle_health(request: web.Request) -> web.Response:
    # Omit session_id from health output — listing session handles would allow
    # credential enumeration by anyone who can reach the endpoint.
    sessions = [
        {
            "username": state.username,
            "client_id": state.client_id,
            "tenant_id": state.tenant_id,
            "authenticated": state.authenticated,
            "expires_at": state.expires_at_iso,
        }
        for state in _sessions.values()
    ]
    return web.Response(
        status=200,
        content_type="application/json",
        text=json.dumps({
            "status": "ok",
            "sessions": sessions,
            "pending_flows": len(_pending),
        }),
    )


# ── OAuth redirect callback server (port 51247) ───────────────────────────────

async def handle_oauth_callback(request: web.Request) -> web.Response:
    params = dict(request.rel_url.query)
    error = params.get("error")

    if error:
        log.error("OAuth callback error: %s — %s", error, params.get("error_description", ""))
        return web.Response(
            status=400,
            content_type="text/html",
            text=(
                "<h1>Authentication failed</h1>"
                f"<p><b>{error}</b>: {params.get('error_description', '')}</p>"
                "<p>You may close this window and check the token manager logs.</p>"
            ),
        )

    state_param = params.get("state")
    matching: PendingFlow | None = None
    for pending in _pending.values():
        if pending.auth_code_flow and pending.auth_code_flow.get("state") == state_param:
            matching = pending
            break

    if not matching:
        log.error("OAuth callback: no pending flow matching state=%r", state_param)
        return web.Response(
            status=400,
            content_type="text/html",
            text=(
                "<h1>Authentication failed</h1>"
                "<p>No pending auth flow found. Did the flow expire or was it already completed?</p>"
            ),
        )

    flow = matching.auth_code_flow
    matching.auth_code_flow = None  # clear before await

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: matching.app.acquire_token_by_auth_code_flow(flow, params),
    )

    if result and "access_token" in result:
        accounts = matching.app.get_accounts()
        username = accounts[0].get("username", "") if accounts else ""
        _promote_to_session(matching, username, result)
        _completed[matching.session_id] = username
        _completed_at[matching.session_id] = time.time()
        log.info(
            "Browser callback completed: session_id=%s username=%s",
            matching.session_id[:8], username,
        )
        return web.Response(
            status=200,
            content_type="text/html",
            text=(
                "<h1>Authentication successful!</h1>"
                "<p>You may close this window and return to the terminal.</p>"
            ),
        )

    err_desc = result.get("error_description", str(result)) if result else "no result"
    log.error(
        "Browser flow token exchange failed: session_id=%s error=%s",
        matching.session_id[:8], err_desc,
    )
    return web.Response(
        status=400,
        content_type="text/html",
        text=(
            "<h1>Authentication failed</h1>"
            f"<p>{err_desc}</p>"
            "<p>You may close this window and check the token manager logs.</p>"
        ),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    global _cache
    _cache = load_cache()

    # Restore sessions from persisted config file. Each entry records the
    # session_id that the sidecar already knows, so the session UUID env var
    # in the sidecar continues to work across token manager restarts without
    # requiring re-onboarding.
    session_configs = _load_session_configs()
    if session_configs:
        log.info("Restoring %d session(s) from %s", len(session_configs), SESSION_CONFIG_FILE)
    for cfg in session_configs:
        sid = cfg.get("session_id")
        client_id = cfg.get("client_id")
        tenant_id = cfg.get("tenant_id")
        login_hint = cfg.get("login_hint", "")
        if not (sid and client_id and tenant_id):
            log.warning("Skipping malformed session config: %s", cfg)
            continue
        app = _build_msal_app(client_id, tenant_id, None, _cache)
        accounts = app.get_accounts(username=login_hint) if login_hint else app.get_accounts()
        if not accounts and login_hint:
            accounts = app.get_accounts()
        restored = False
        for account in accounts:
            username = account.get("username", "")
            result = app.acquire_token_silent(REFRESH_SCOPES, account=account)
            if result and "access_token" in result:
                state = AppState(
                    session_id=sid,
                    client_id=client_id,
                    tenant_id=tenant_id,
                    username=username,
                    client_secret=None,
                    app=app,
                    cache=_cache,
                )
                _apply_token(state, result)
                save_cache(state.cache)
                _sessions[sid] = state
                state.refresh_task = asyncio.get_event_loop().create_task(
                    _refresh_loop(state), name=f"refresh-{sid[:8]}"
                )
                log.info(
                    "Session restored: session_id=%s username=%s expires=%s",
                    sid, username, state.expires_at_iso,
                )
                restored = True
                break
        if not restored:
            log.warning(
                "Silent restore failed for session_id=%s login_hint=%s — re-auth required",
                sid, login_hint or "(none)",
            )

    # Main API server
    api_app = web.Application()
    api_app.router.add_post("/auth/start", handle_auth_start)
    api_app.router.add_get("/auth/poll", handle_auth_poll)
    api_app.router.add_get("/token", handle_token)
    api_app.router.add_get("/health", handle_health)

    runner = web.AppRunner(api_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    log.info("Token manager listening on 0.0.0.0:%d", HTTP_PORT)

    # OAuth redirect callback server
    callback_app = web.Application()
    callback_app.router.add_get("/", handle_oauth_callback)
    callback_runner = web.AppRunner(callback_app)
    await callback_runner.setup()
    callback_site = web.TCPSite(callback_runner, "0.0.0.0", OAUTH_REDIRECT_PORT)
    await callback_site.start()
    log.info("OAuth redirect listener on 0.0.0.0:%d", OAUTH_REDIRECT_PORT)

    asyncio.get_event_loop().create_task(_cleanup_pending(), name="cleanup-pending")

    while True:
        await asyncio.sleep(3600)


async def _wait_for_device_flow(pending: PendingFlow) -> None:
    """Background task: block on device flow completion for the startup default flow."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: pending.app.acquire_token_by_device_flow(pending.device_flow)
    )
    if result and "access_token" in result:
        accounts = pending.app.get_accounts()
        username = accounts[0].get("username", "") if accounts else ""
        _promote_to_session(pending, username, result)
        log.info(
            "Default device flow authenticated: session_id=%s username=%s expires=%s",
            pending.session_id, username, _sessions[pending.session_id].expires_at_iso,
        )
    else:
        log.error(
            "Device code flow failed: %s",
            result.get("error_description", result) if result else "no result",
        )


if __name__ == "__main__":
    asyncio.run(main())
