# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Outlook bridge — polls Microsoft Graph for new mail, relays to the Hermes
# HTTP API, sends replies. Authorization is `Bearer
# openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN`: the OpenShell L7 proxy
# substitutes the placeholder with a live, gateway-refreshed delegated access
# token on egress. The bridge never holds a real token.

import asyncio
import datetime
import json
import logging
import os
import pathlib
import re
import signal
import ssl
import sys
import time

import aiofiles
import aiohttp
from markdown_it import MarkdownIt

_md = MarkdownIt().enable("table")


def _email_html(text: str) -> str:
    """Convert a markdown reply to an Outlook-safe HTML email."""
    body = _md.render(text)

    # Inject inline styles on table elements so Outlook renders them correctly.
    # <style> blocks work in modern Outlook but table borders require inline styles.
    body = re.sub(r"<table>", '<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:13px;">', body)
    body = re.sub(r"<th>", '<th style="padding:7px 10px;border:1px solid #ddd;background:#f0f0f0;font-weight:600;text-align:left;">', body)
    body = re.sub(r"<td>", '<td style="padding:7px 10px;border:1px solid #ddd;text-align:left;">', body)
    body = re.sub(r"<pre>", '<pre style="background:#f4f4f4;padding:12px;border-left:3px solid #bbb;font-family:monospace;font-size:13px;white-space:pre-wrap;margin:10px 0;">', body)
    body = re.sub(r"<code>", '<code style="background:#f4f4f4;padding:1px 4px;font-family:monospace;border-radius:2px;">', body)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #1a1a1a; margin: 0; padding: 0; }}
  p {{ margin: 8px 0; line-height: 1.6; }}
  ul, ol {{ margin: 6px 0; padding-left: 22px; }}
  li {{ margin: 3px 0; line-height: 1.5; }}
  h1 {{ font-size: 22px; margin: 16px 0 8px; }}
  h2 {{ font-size: 18px; margin: 16px 0 8px; }}
  h3 {{ font-size: 15px; margin: 12px 0 6px; }}
  hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 16px 0; }}
  blockquote {{ margin: 8px 0 8px 16px; padding-left: 12px; border-left: 3px solid #ccc; color: #555; }}
</style>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;">
<table cellpadding="0" cellspacing="0" width="100%" style="background:#f5f5f5;padding:24px 12px;">
  <tr><td align="center">
    <table cellpadding="0" cellspacing="0" width="640"
           style="background:#ffffff;border:1px solid #e0e0e0;border-radius:4px;">
      <tr>
        <td style="padding:32px 40px;color:#1a1a1a;font-size:14px;line-height:1.6;">
{body}
        </td>
      </tr>
      <tr>
        <td style="padding:12px 40px;background:#f8f8f8;border-top:1px solid #ebebeb;
                   font-size:11px;color:#999;text-align:center;">
          Sent by Hermes &middot; NVIDIA NemoClaw
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""

logging.basicConfig(
    level=logging.INFO,
    format="[outlook-bridge] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── Auth placeholder ─────────────────────────────────────────────────────────
# Send the CANONICAL (unscoped) OpenShell placeholder, NOT the value OpenShell
# injects into MS_GRAPH_ACCESS_TOKEN. OpenShell injects a *revision-pinned*
# placeholder (`openshell:resolve:env:v<rev>_MS_GRAPH_ACCESS_TOKEN`) fixed at
# process-start and never mutates a running process's env afterward — see the
# OpenShell docs, sandboxes/providers-v2.mdx "Runtime Limitations": "already-
# running processes keep the environment they started with ... restart that
# process". So for this long-running poller, once the gateway's OAuth refresh
# rotates the token the pinned revision's value expires and the L7 proxy fails
# closed (same doc: "stale placeholders fail closed") — every Graph call then
# dies with ServerDisconnectedError ~1h in, until the sandbox is recreated.
#
# Re-reading os.environ does NOT help: the env holds only a placeholder string
# (never a token), frozen at process spawn, so it returns the same pinned
# revision forever. The token is substituted at the proxy per request, so the
# only lever is WHICH placeholder we emit. `openshell:resolve:env:KEY` is the
# documented canonical/stable form (OpenShell docs: reference/policy-schema.mdx,
# sandboxes/policies.mdx) and the proxy resolves it to the CURRENT refreshed
# token every request (kept fresh on each sandbox poll). It's the same floating
# form this repo already uses for the ATIF bearer (AWS_SESSION_TOKEN, see
# agents/hermes/start.sh).
#
# Do NOT change this back to os.environ.get("MS_GRAPH_ACCESS_TOKEN", ...).
MS_GRAPH_ACCESS_TOKEN = "openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN"

# ── Mailbox config ───────────────────────────────────────────────────────────
# OUTLOOK_TARGET_MAILBOX / OUTLOOK_REPLY_TO are non-secret per-user config,
# injected at sandbox-create time via `-- env` and read from os.environ below.
# Unlike MS_GRAPH_ACCESS_TOKEN above (a real credential the L7 proxy substitutes
# at egress), these are NOT proxy-rewritten — even though the mailbox lands in
# the Graph URL path, it is not a provider credential. The `openshell:resolve:`
# string is only a sentinel for the unconfigured case: the helpers below detect
# it and fall back to /me (mailbox) or the job's `to` field (reply-to).
# Omit OUTLOOK_TARGET_MAILBOX to use /me (the authenticated account's inbox).
_TARGET_MAILBOX = "openshell:resolve:env:OUTLOOK_TARGET_MAILBOX"
# OUTLOOK_REPLY_TO: address used as the recipient for outbound scheduled-job
# emails. Separate from OUTLOOK_TARGET_MAILBOX so you can poll a bot inbox
# while sending results to a personal account. Falls back to OUTLOOK_TARGET_MAILBOX
# and then to "me" (the authenticated account).
_REPLY_TO_PLACEHOLDER = "openshell:resolve:env:OUTLOOK_REPLY_TO"

def _mailbox_base() -> str:
    """Graph API base path for the target mailbox."""
    raw = os.environ.get("OUTLOOK_TARGET_MAILBOX", _TARGET_MAILBOX)
    # Fall back to /me when unset, literally "me", or still an unrewritten placeholder.
    if not raw or raw == "me" or raw.startswith("openshell:resolve:"):
        return "me"
    return f"users/{raw}"

def _reply_to_address() -> str | None:
    """Outbound recipient for scheduled jobs. None means use the job's 'to' field."""
    raw = os.environ.get("OUTLOOK_REPLY_TO", _REPLY_TO_PLACEHOLDER)
    if not raw or raw.startswith("openshell:resolve:"):
        return None
    return raw

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _graph_url(path_or_url: str) -> str:
    """Resolve a relative path or absolute Graph URL."""
    if path_or_url.startswith("http"):
        return path_or_url
    return f"{GRAPH_BASE}/{path_or_url.lstrip('/')}"


# ── Runtime config ───────────────────────────────────────────────────────────
HERMES_URL      = "http://127.0.0.1:18642/v1/chat/completions"
HEALTH_URL      = "http://127.0.0.1:18642/health"
HERMES_API_KEY  = "nemoclaw-internal"

MIN_POLL_INTERVAL      = 5
MAX_POLL_INTERVAL      = 30
BACKOFF_AFTER          = 3
MAX_CONCURRENT_MESSAGES = 5  # max simultaneous ask_hermes calls

HEALTH_RETRY_SECONDS = 5
HEALTH_MAX_RETRIES = 60
BOOTSTRAP_RETRY_SECONDS = 15
BOOTSTRAP_RETRY_WINDOW_SECONDS = 300

HERMES_HOME = os.environ.get("HERMES_HOME", "/sandbox/.hermes-data")
JOBS_FILE = os.path.join(HERMES_HOME, "cron", "outlook-jobs.json")
SENDER_POLL_INTERVAL = 30

# ── Delta link persistence ───────────────────────────────────────────────────
_DELTA_LINK_FILE = pathlib.Path(HERMES_HOME) / "outlook" / "delta-link.json"


async def _load_delta_link() -> str | None:
    try:
        async with aiofiles.open(_DELTA_LINK_FILE) as f:
            return json.loads(await f.read())["delta_link"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


async def _save_delta_link(link: str) -> None:
    try:
        _DELTA_LINK_FILE.parent.mkdir(parents=True, exist_ok=True)  # single syscall, wrapping overhead would dominate
        async with aiofiles.open(_DELTA_LINK_FILE, "w") as f:
            await f.write(json.dumps({"delta_link": link}))
    except OSError:
        log.warning("Could not persist delta link to %s", _DELTA_LINK_FILE)


# ── Module-level state ───────────────────────────────────────────────────────
_client: aiohttp.ClientSession | None = None
_delta_link: str | None = None
_consecutive_empty: int = 0
ALLOWED_SENDERS: set[str] = set()
_in_flight: set[str] = set()
_sem = asyncio.Semaphore(MAX_CONCURRENT_MESSAGES)

# create_task returns a weakref; without a strong ref the GC can drop in-flight tasks.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ── Startup health check ─────────────────────────────────────────────────────

async def wait_for_hermes() -> None:
    for attempt in range(HEALTH_MAX_RETRIES):
        try:
            async with _client.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    log.info("Hermes gateway is healthy")
                    return
        except aiohttp.ClientError:
            pass
        log.info("Waiting for Hermes gateway (attempt %d/%d)…", attempt + 1, HEALTH_MAX_RETRIES)
        await asyncio.sleep(HEALTH_RETRY_SECONDS)
    log.error("Hermes gateway did not become healthy — exiting")
    sys.exit(1)


# ── Microsoft Graph helpers ──────────────────────────────────────────────────

async def _graph_request(method: str, path_or_url: str, **kwargs) -> dict | None:
    url = _graph_url(path_or_url)
    headers = {
        "Authorization": f"Bearer {MS_GRAPH_ACCESS_TOKEN}",
        **kwargs.pop("headers", {}),
    }
    for attempt in range(2):
        async with _client.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status == 429 and attempt == 0:
                retry_after = int(resp.headers.get("Retry-After", 60))
                log.warning("Graph API rate limited — retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            body = await resp.read()
            return await resp.json() if body else None
    return None  # unreachable; loop only exits via early return


async def graph_get(path_or_url: str) -> dict:
    return await _graph_request("get", path_or_url, timeout=aiohttp.ClientTimeout(total=15))


async def graph_post(path_or_url: str, payload: dict) -> None:
    await _graph_request(
        "post", path_or_url,
        json=payload, headers={"Content-Type": "application/json"},
        timeout=aiohttp.ClientTimeout(total=15),
    )


async def graph_patch(path_or_url: str, payload: dict) -> None:
    await _graph_request(
        "patch", path_or_url,
        json=payload, headers={"Content-Type": "application/json"},
        timeout=aiohttp.ClientTimeout(total=10),
    )


# ── Allowed-senders resolution ───────────────────────────────────────────────

async def resolve_allowed_senders() -> set[str]:
    """Return the set of allowed sender addresses.

    Reads OUTLOOK_ALLOWED_SENDERS env var (comma-separated) if set.
    Otherwise waits for the first email in the target inbox and uses
    that sender — preserving the original "activate by sending a message" UX.
    """
    configured = os.environ.get("OUTLOOK_ALLOWED_SENDERS", "").strip()
    if configured:
        senders = {addr.strip().lower() for addr in configured.split(",") if addr.strip()}
        log.info("Allowed senders from OUTLOOK_ALLOWED_SENDERS: %s", senders)
        return senders

    # Discover from inbox — wait for first email
    logged_waiting = False
    while True:
        data = await graph_get(
            f"{_mailbox_base()}/mailFolders/inbox/messages"
            "?$top=10&$select=from&$orderby=receivedDateTime desc"
        )
        for msg in data.get("value", []):
            address = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
            if "@" in address:
                log.info("Allowed senders discovered via inbox: %s", address)
                return {address}
        if not logged_waiting:
            log.info(
                "Inbox empty — waiting for first email to activate the bridge. "
                "Send a message or set OUTLOOK_ALLOWED_SENDERS to skip discovery."
            )
            logged_waiting = True
        await asyncio.sleep(SENDER_POLL_INTERVAL)


async def initialize_allowed_senders(shutdown: asyncio.Event) -> set[str]:
    deadline = time.monotonic() + BOOTSTRAP_RETRY_WINDOW_SECONDS
    last_error: Exception | None = None
    while not shutdown.is_set():
        try:
            return await resolve_allowed_senders()
        except aiohttp.ServerDisconnectedError:
            last_error = sys.exc_info()[1]
            log.warning(
                "Outlook bridge bootstrap blocked by proxy. "
                "Retrying in %ds; resolves once policy presets finish loading.",
                BOOTSTRAP_RETRY_SECONDS,
            )
        except aiohttp.ClientResponseError as exc:
            last_error = exc
            log.warning(
                "Graph request returned HTTP %d. Retrying in %ds.",
                exc.status, BOOTSTRAP_RETRY_SECONDS,
            )
        except aiohttp.ClientError as exc:
            last_error = exc
            log.warning(
                "Bridge bootstrap request failed (%s). Retrying in %ds.",
                exc.__class__.__name__, BOOTSTRAP_RETRY_SECONDS,
            )
        if time.monotonic() >= deadline:
            break
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=BOOTSTRAP_RETRY_SECONDS)
        except asyncio.TimeoutError:
            pass
    if shutdown.is_set():
        raise asyncio.CancelledError
    assert last_error is not None
    raise last_error


# ── Hermes relay ─────────────────────────────────────────────────────────────

async def ask_hermes(prompt: str) -> tuple[str | None, str | None]:
    try:
        async with _client.post(
            HERMES_URL,
            json={"model": "hermes-agent", "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {HERMES_API_KEY}"},
            timeout=aiohttp.ClientTimeout(total=1200),
        ) as resp:
            resp.raise_for_status()
            session_id = resp.headers.get("X-Hermes-Session-Id")
            payload = await resp.json()
            return payload["choices"][0]["message"]["content"], session_id
    except Exception:
        log.exception("Error calling Hermes API")
        return None, None


# ── Inbox polling ────────────────────────────────────────────────────────────

async def poll_inbox() -> int:
    global _delta_link

    path = (
        _delta_link
        or f"{_mailbox_base()}/mailFolders/inbox/messages/delta"
           "?$select=id,subject,body,from,isRead"
    )

    messages: list[dict] = []
    try:
        data = await graph_get(path)
    except aiohttp.ClientResponseError as exc:
        if exc.status in (400, 410):
            log.warning("Delta link expired (status %d) — resetting state", exc.status)
            _delta_link = None
            return 0
        raise

    while True:
        messages.extend(
            msg for msg in data.get("value", [])
            if not msg.get("@removed") and not msg.get("isRead", False)
        )
        if next_link := data.get("@odata.nextLink"):
            data = await graph_get(next_link)
        else:
            break

    if dl := data.get("@odata.deltaLink"):
        _delta_link = dl
        await _save_delta_link(dl)

    new_messages = [m for m in messages if m["id"] not in _in_flight]
    for msg in new_messages:
        _spawn(_handle_message_guarded(msg))

    return len(new_messages)


async def _handle_message(msg: dict) -> None:
    sender = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
    if ALLOWED_SENDERS and sender not in ALLOWED_SENDERS:
        log.info("Ignoring message from non-allowed sender: %s", sender)
        await _mark_read(msg["id"])
        return

    subject = msg.get("subject", "(no subject)")
    body = msg.get("body", {}).get("content", "")
    prompt = f"Email from {sender}\nSubject: {subject}\n\n{body}"

    log.info("Processing message from %s: %s", sender, subject)
    reply, _ = await ask_hermes(prompt)
    if reply:
        await _send_reply(msg["id"], reply)
    await _mark_read(msg["id"])


async def _handle_message_guarded(msg: dict) -> None:
    msg_id = msg["id"]
    _in_flight.add(msg_id)
    try:
        async with _sem:
            await _handle_message(msg)
    except Exception:
        log.exception("Error handling message %s", msg_id)
    finally:
        _in_flight.discard(msg_id)


async def _send_reply(msg_id: str, reply: str) -> None:
    try:
        await graph_post(
            f"{_mailbox_base()}/messages/{msg_id}/reply",
            {"message": {"body": {"contentType": "html", "content": _email_html(reply)}}},
        )
        log.info("Sent reply to message %s", msg_id)
    except Exception:
        log.exception("Error sending reply for message %s", msg_id)


async def _mark_read(msg_id: str) -> None:
    try:
        await graph_patch(f"{_mailbox_base()}/messages/{msg_id}", {"isRead": True})
    except Exception:
        log.exception("Error marking message %s as read", msg_id)


# ── Adaptive poll loop ───────────────────────────────────────────────────────

async def _poll_loop(shutdown: asyncio.Event) -> None:
    global _consecutive_empty
    while not shutdown.is_set():
        try:
            count = await poll_inbox()
        except Exception:
            log.exception("Error during inbox poll")
            count = 0

        if count > 0:
            _consecutive_empty = 0
            interval = MIN_POLL_INTERVAL
        else:
            _consecutive_empty += 1
            interval = MAX_POLL_INTERVAL if _consecutive_empty >= BACKOFF_AFTER else MIN_POLL_INTERVAL

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


# ── Scheduled jobs ───────────────────────────────────────────────────────────

async def _load_jobs() -> list[dict]:
    if not os.path.exists(JOBS_FILE):  # single syscall, wrapping overhead would dominate
        log.info("No jobs file at %s — scheduled jobs disabled", JOBS_FILE)
        return []
    try:
        async with aiofiles.open(JOBS_FILE) as f:
            jobs = json.loads(await f.read())
        for job in jobs:
            log.info("Loaded job '%s' at %s daily", job.get("name", "?"), job.get("time", "?"))
        return jobs
    except Exception:
        log.exception("Failed to load %s", JOBS_FILE)
        return []


async def _job_loop(jobs: list[dict], shutdown: asyncio.Event) -> None:
    last_day = -1
    while not shutdown.is_set():
        try:
            now = datetime.datetime.now()
            if now.day != last_day:
                for job in jobs:
                    job.pop("_fired_today", None)
                last_day = now.day
            time_str = now.strftime("%H:%M")
            for job in jobs:
                if job.get("time") == time_str and not job.get("_fired_today"):
                    job["_fired_today"] = True
                    _spawn(_run_job(job))
        except Exception:
            log.exception("Error in job loop tick")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


async def _run_job(job: dict) -> None:
    prompt = job.get("prompt", "")
    if not prompt:
        log.warning("Job '%s' has no prompt — skipping", job.get("name", "?"))
        return
    log.info("Running scheduled job: %s", job.get("name", prompt[:50]))
    reply, _ = await ask_hermes(prompt)
    if not reply:
        return
    try:
        # Precedence: job-level "to" > OUTLOOK_REPLY_TO > OUTLOOK_TARGET_MAILBOX > "me"
        to_address = job.get("to") or _reply_to_address() or os.environ.get("OUTLOOK_TARGET_MAILBOX") or "me"
        subject = job.get("subject", f"Scheduled: {job.get('name', 'report')}")
        await graph_post(
            f"{_mailbox_base()}/sendMail",
            {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": _email_html(reply)},
                    "toRecipients": [{"emailAddress": {"address": to_address}}],
                }
            },
        )
        log.info("Sent scheduled email for job '%s' to %s", job.get("name", "?"), to_address)
    except Exception:
        log.exception("Error sending scheduled email for job '%s'", job.get("name", "?"))


# ── Main ─────────────────────────────────────────────────────────────────────

async def _async_main() -> None:
    global _client, _delta_link, ALLOWED_SENDERS
    log.info(
        "Outlook bridge starting (HERMES_HOME=%s, GRAPH_BASE=%s, mailbox=%s)",
        HERMES_HOME, GRAPH_BASE, _mailbox_base(),
    )

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: (log.info("Shutdown signal received"), shutdown.set()))

    # Reject any peer that can't do TLS 1.3 — modern peer set, fail loud on degradation.
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    # trust_env=True so HTTPS_PROXY (OpenShell L7) is honored; aiohttp ignores it by default.
    async with aiohttp.ClientSession(
        trust_env=True,
        connector=aiohttp.TCPConnector(ssl=ssl_ctx),
    ) as client:
        _client = client
        await wait_for_hermes()

        # Restore delta link from previous run — avoids re-processing old mail
        _delta_link = await _load_delta_link()
        if _delta_link:
            log.info("Restored delta link from %s", _DELTA_LINK_FILE)

        ALLOWED_SENDERS = await initialize_allowed_senders(shutdown)
        jobs = await _load_jobs()
        log.info(
            "Bridge ready — polling inbox (%ds active / %ds quiet)",
            MIN_POLL_INTERVAL, MAX_POLL_INTERVAL,
        )
        coros = [_poll_loop(shutdown)]
        if jobs:
            coros.append(_job_loop(jobs, shutdown))
        await asyncio.gather(*coros)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
