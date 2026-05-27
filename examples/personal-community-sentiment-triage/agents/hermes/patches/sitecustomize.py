# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Patch Hermes Python transports for NemoClaw-managed messaging egress."""

from __future__ import annotations

import re
import urllib.request


SLACK_PLACEHOLDER_RE = re.compile(
    r"\b(?:xoxb|xapp)-OPENSHELL-RESOLVE-ENV-(SLACK_(?:BOT|APP)_TOKEN)\b"
)
SLACK_FAST_PATH = "OPENSHELL-RESOLVE-ENV-SLACK_"


def _rewrite_slack_string(value: str) -> str:
    if SLACK_FAST_PATH not in value:
        return value
    return SLACK_PLACEHOLDER_RE.sub(r"openshell:resolve:env:\1", value)


def _rewrite_slack_value(value):
    if isinstance(value, str):
        return _rewrite_slack_string(value)
    if isinstance(value, bytes):
        if SLACK_FAST_PATH.encode("ascii") not in value:
            return value
        try:
            return _rewrite_slack_string(value.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            return value
    if isinstance(value, bytearray):
        as_bytes = bytes(value)
        rewritten = _rewrite_slack_value(as_bytes)
        return bytearray(rewritten) if rewritten != as_bytes else value
    if isinstance(value, tuple):
        return tuple(_rewrite_slack_value(item) for item in value)
    if isinstance(value, list):
        return [_rewrite_slack_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_slack_value(item) for key, item in value.items()}
    return value


def _rewrite_slack_headers(headers):
    if not headers:
        return headers
    if isinstance(headers, dict):
        for key in list(headers.keys()):
            headers[key] = _rewrite_slack_value(headers[key])
        return headers
    if hasattr(headers, "items") and hasattr(headers, "__setitem__"):
        try:
            for key, value in list(headers.items()):
                headers[key] = _rewrite_slack_value(value)
            return headers
        except (AttributeError, KeyError, TypeError):
            pass
    if isinstance(headers, (list, tuple)):
        return type(headers)((key, _rewrite_slack_value(value)) for key, value in headers)
    return headers


def _rewrite_slack_url(url):
    if not isinstance(url, str):
        text = str(url)
        rewritten = _rewrite_slack_string(text)
        return rewritten if rewritten != text else url
    return _rewrite_slack_string(url)


def _rewrite_slack_kwargs(kwargs):
    if "headers" in kwargs:
        kwargs["headers"] = _rewrite_slack_headers(kwargs["headers"])
    for key in ("data", "json", "params", "content"):
        if key in kwargs:
            kwargs[key] = _rewrite_slack_value(kwargs[key])
    return kwargs


try:
    import aiohttp
except Exception:
    aiohttp = None


_original_urllib_request_init = urllib.request.Request.__init__
_original_urllib_add_header = urllib.request.Request.add_header
_original_urllib_add_unredirected_header = urllib.request.Request.add_unredirected_header


def _nemoclaw_urllib_request_init(
    self,
    url,
    data=None,
    headers=None,
    origin_req_host=None,
    unverifiable=False,
    method=None,
):
    headers = {} if headers is None else headers
    return _original_urllib_request_init(
        self,
        _rewrite_slack_url(url),
        data=_rewrite_slack_value(data),
        headers=_rewrite_slack_headers(headers),
        origin_req_host=origin_req_host,
        unverifiable=unverifiable,
        method=method,
    )


def _nemoclaw_urllib_add_header(self, key, val):
    return _original_urllib_add_header(self, key, _rewrite_slack_value(val))


def _nemoclaw_urllib_add_unredirected_header(self, key, val):
    return _original_urllib_add_unredirected_header(self, key, _rewrite_slack_value(val))


urllib.request.Request.__init__ = _nemoclaw_urllib_request_init
urllib.request.Request.add_header = _nemoclaw_urllib_add_header
urllib.request.Request.add_unredirected_header = _nemoclaw_urllib_add_unredirected_header


try:
    import requests.sessions as _requests_sessions
except Exception:
    _requests_sessions = None

if _requests_sessions is not None:
    _original_requests_request = _requests_sessions.Session.request

    def _nemoclaw_requests_request(self, method, url, **kwargs):
        return _original_requests_request(
            self, method, _rewrite_slack_url(url), **_rewrite_slack_kwargs(kwargs)
        )

    _requests_sessions.Session.request = _nemoclaw_requests_request


try:
    import httpx as _httpx
except Exception:
    _httpx = None

if _httpx is not None:
    _original_httpx_client_request = _httpx.Client.request
    _original_httpx_async_client_request = _httpx.AsyncClient.request

    def _nemoclaw_httpx_client_request(self, method, url, *args, **kwargs):
        return _original_httpx_client_request(
            self, method, _rewrite_slack_url(url), *args, **_rewrite_slack_kwargs(kwargs)
        )

    async def _nemoclaw_httpx_async_client_request(self, method, url, *args, **kwargs):
        return await _original_httpx_async_client_request(
            self, method, _rewrite_slack_url(url), *args, **_rewrite_slack_kwargs(kwargs)
        )

    _httpx.Client.request = _nemoclaw_httpx_client_request
    _httpx.AsyncClient.request = _nemoclaw_httpx_async_client_request


if aiohttp is not None:
    _original_request = aiohttp.ClientSession._request

    async def _nemoclaw_request(self, method, str_or_url, **kwargs):
        return await _original_request(
            self, method, _rewrite_slack_url(str_or_url), **_rewrite_slack_kwargs(kwargs)
        )

    aiohttp.ClientSession._request = _nemoclaw_request


# ---------------------------------------------------------------------------
# Slack catch-all slash command — Hermes only registers "/hermes" as its bolt
# command handler. Any workspace-specific command name (e.g. /my-assistant)
# produces an "Unhandled request" warning. After SlackAdapter connects,
# register a catch-all that routes every other slash command through the same
# response path.
def _patch_slack_commands() -> None:
    try:
        from gateway.platforms.slack import SlackAdapter
        _orig_connect = SlackAdapter.connect

        async def _patched_connect(self):
            result = await _orig_connect(self)
            if getattr(self, "_app", None) is not None:
                @self._app.command(re.compile(".+"))
                async def _handle_unknown_command(ack, command, respond):
                    await ack()
                    cmd = command.get("command", "this command")
                    await respond(
                        f"I don't recognize `{cmd}`. "
                        "Send me a *direct message* or @mention me to chat"
                    )
            return result

        SlackAdapter.connect = _patched_connect
    except Exception:
        pass


_patch_slack_commands()
