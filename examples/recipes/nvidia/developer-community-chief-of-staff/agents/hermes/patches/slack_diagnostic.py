# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Sanitized stage instrumentation for guided Slack delivery diagnostics."""

from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from typing import Any


DIAGNOSTIC_LOG = Path("/tmp/nemoclaw-slack-diagnostic.jsonl")
SOCKET_STATUS = Path("/tmp/nemoclaw-slack-socket-status.json")
DIAGNOSTIC_TTL_SECONDS = 600
DIAGNOSTIC_LOG_MAX_BYTES = 1024 * 1024
_DIAGNOSTIC_RE = re.compile(
    r"(?<![A-Z0-9])NC-[A-F0-9]{8}(?![A-Z0-9])",
    re.IGNORECASE,
)
_STAGES = {
    "socket_mode_connection",
    "inbound_event_receipt",
    "hermes_dispatch",
    "inference",
    "outbound_response",
}
_STATUSES = {"started", "confirmed", "failed"}


def diagnostic_id(text: Any) -> str:
    """Return the first diagnostic ID in *text* without retaining other text."""
    match = _DIAGNOSTIC_RE.search(str(text or ""))
    return match.group(0).upper() if match else ""


def _open_log() -> int:
    parent = DIAGNOSTIC_LOG.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if DIAGNOSTIC_LOG.is_symlink():
        raise OSError("diagnostic log path is a symbolic link")

    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(DIAGNOSTIC_LOG, flags, 0o600)
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(descriptor)
        raise OSError("diagnostic log path is not a regular file")
    os.fchmod(descriptor, 0o600)
    if file_stat.st_size > DIAGNOSTIC_LOG_MAX_BYTES:
        os.ftruncate(descriptor, 0)
    return descriptor


def _write_socket_status(payload: bytes) -> None:
    if SOCKET_STATUS.is_symlink():
        return
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(SOCKET_STATUS, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload)
    except OSError:
        return
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def record_stage(
    test_id: str,
    stage: str,
    *,
    status: str = "confirmed",
    error_type: str = "",
) -> None:
    """Append one bounded event without message content or credentials."""
    if stage not in _STAGES or status not in _STATUSES:
        return
    normalized_id = diagnostic_id(test_id) if test_id else ""
    if test_id and not normalized_id:
        return

    import json

    event = {
        "diagnostic_id": normalized_id,
        "stage": stage,
        "status": status,
        "timestamp": round(time.time(), 3),
        "pid": os.getpid(),
    }
    if error_type:
        event["error_type"] = re.sub(r"[^A-Za-z0-9_.-]", "", error_type)[:80]

    encoded = (json.dumps(event, sort_keys=True) + "\n").encode()
    if stage == "socket_mode_connection":
        _write_socket_status(encoded)

    descriptor = -1
    try:
        descriptor = _open_log()
        os.write(descriptor, encoded)
    except OSError:
        # Diagnostics must never interrupt Slack delivery.
        return
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _event_text(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("text") or "")
    return str(getattr(event, "text", "") or "")


def _event_route(event: Any) -> tuple[str, str, str]:
    metadata = getattr(event, "metadata", None) or {}
    source = getattr(event, "source", None)
    team_id = str(
        metadata.get("slack_team_id")
        or getattr(source, "scope_id", "")
        or ""
    )
    channel_id = str(
        metadata.get("slack_channel_id")
        or getattr(source, "chat_id", "")
        or ""
    )
    thread_id = str(
        metadata.get("slack_thread_ts")
        or getattr(source, "thread_id", "")
        or getattr(event, "message_id", "")
        or ""
    )
    return team_id, channel_id, thread_id


def _remember_route(adapter: Any, event: Any, test_id: str) -> None:
    routes = getattr(adapter, "_nemoclaw_diagnostic_routes", None)
    if routes is None:
        routes = {}
        adapter._nemoclaw_diagnostic_routes = routes

    now = time.monotonic()
    for key, (_stored_id, created) in list(routes.items()):
        if now - created > DIAGNOSTIC_TTL_SECONDS:
            routes.pop(key, None)

    team_id, channel_id, thread_id = _event_route(event)
    if not channel_id:
        return
    routes[(team_id, channel_id, thread_id)] = (test_id, now)
    routes[(team_id, channel_id, "")] = (test_id, now)
    if team_id:
        routes[("", channel_id, thread_id)] = (test_id, now)
        routes[("", channel_id, "")] = (test_id, now)


def _route_id(adapter: Any, chat_id: str, metadata: Any) -> str:
    routes = getattr(adapter, "_nemoclaw_diagnostic_routes", {})
    metadata = metadata or {}
    team_id = str(metadata.get("slack_team_id") or "")
    thread_id = str(
        metadata.get("slack_thread_ts")
        or metadata.get("thread_id")
        or ""
    )
    channel_id = str(chat_id or metadata.get("slack_channel_id") or "")
    now = time.monotonic()
    for key in (
        (team_id, channel_id, thread_id),
        (team_id, channel_id, ""),
        ("", channel_id, thread_id),
        ("", channel_id, ""),
    ):
        stored = routes.get(key)
        if stored and now - stored[1] <= DIAGNOSTIC_TTL_SECONDS:
            return str(stored[0])
    return ""


def install_adapter_instrumentation(adapter_class: type) -> bool:
    """Install feature-detected hooks on a Hermes Slack adapter class."""
    if adapter_class.__dict__.get("_nemoclaw_slack_diagnostic_installed"):
        return True

    method_names = (
        "_handle_slack_message",
        "_handle_slash_command",
        "handle_message",
        "set_message_handler",
        "send",
    )
    originals = {name: getattr(adapter_class, name, None) for name in method_names}
    if not all(callable(method) for method in originals.values()):
        return False

    async def _diagnostic_slack_message(self, event, payload=None):
        test_id = diagnostic_id(_event_text(event))
        if test_id:
            record_stage(test_id, "inbound_event_receipt")
        return await originals["_handle_slack_message"](self, event, payload)

    async def _diagnostic_slash_command(self, command):
        test_id = diagnostic_id(_event_text(command))
        if test_id:
            record_stage(test_id, "inbound_event_receipt")
        return await originals["_handle_slash_command"](self, command)

    async def _diagnostic_handle_message(self, event):
        test_id = diagnostic_id(_event_text(event))
        if test_id:
            _remember_route(self, event, test_id)
            record_stage(test_id, "hermes_dispatch")
        return await originals["handle_message"](self, event)

    def _diagnostic_set_message_handler(self, handler):
        if getattr(handler, "_nemoclaw_slack_diagnostic_handler", False):
            return originals["set_message_handler"](self, handler)

        async def _diagnostic_handler(event):
            test_id = diagnostic_id(_event_text(event))
            if not test_id:
                return await handler(event)
            record_stage(test_id, "inference", status="started")
            try:
                result = await handler(event)
            except Exception as error:
                record_stage(
                    test_id,
                    "inference",
                    status="failed",
                    error_type=type(error).__name__,
                )
                raise
            record_stage(test_id, "inference")
            return result

        _diagnostic_handler._nemoclaw_slack_diagnostic_handler = True
        return originals["set_message_handler"](self, _diagnostic_handler)

    async def _diagnostic_send(
        self,
        chat_id,
        content,
        reply_to=None,
        metadata=None,
    ):
        test_id = _route_id(self, chat_id, metadata)
        try:
            result = await originals["send"](
                self,
                chat_id,
                content,
                reply_to=reply_to,
                metadata=metadata,
            )
        except Exception as error:
            if test_id:
                record_stage(
                    test_id,
                    "outbound_response",
                    status="failed",
                    error_type=type(error).__name__,
                )
            raise

        if test_id:
            record_stage(
                test_id,
                "outbound_response",
                status=("confirmed" if getattr(result, "success", False) else "failed"),
                error_type=("" if getattr(result, "success", False) else "SendResultFailure"),
            )
        return result

    patched_methods = {
        "_handle_slack_message": _diagnostic_slack_message,
        "_handle_slash_command": _diagnostic_slash_command,
        "handle_message": _diagnostic_handle_message,
        "set_message_handler": _diagnostic_set_message_handler,
        "send": _diagnostic_send,
    }
    for name, method in patched_methods.items():
        setattr(adapter_class, name, method)
    adapter_class._nemoclaw_slack_diagnostic_methods = tuple(patched_methods)
    adapter_class._nemoclaw_slack_diagnostic_installed = True
    return True
