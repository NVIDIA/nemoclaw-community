# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
nemo-flow-bridge: in-process Hermes plugin that forwards pre/post_api_request
hooks to NeMo-Flow with the real request body and response body attached.

Under Hermes v0.14.0, plugin hooks carry real data:
  - pre_api_request receives `request_messages` (list of dicts), `user_message`,
    and `conversation_history` — the actual OpenAI-shape messages array Hermes
    is about to send upstream.
  - post_api_request receives `response` (a SimpleNamespace mirroring the
    OpenAI ChatCompletion shape with .choices/.usage/.model/.id) and
    `assistant_message` (a NormalizedResponse with .content/.tool_calls).

NeMo-Flow's Hermes adapter (crates/cli/src/adapters/hermes.rs) flips
`provider_payload_exact` to true and emits Phoenix LLM spans with the full
prompt+completion when it finds `payload.request.body` (pre) or
`payload.response.{raw_response,choices,assistant_message}` (post). This plugin
builds those payload shapes from the in-process kwargs and POSTs them to
`${NEMO_FLOW_GATEWAY_URL}/hooks/hermes` — the URL is exported into the Hermes
child env by the `nemo-flow hermes -- gateway run` wrapper at start.sh.

Failure mode is fail-open: any exception is swallowed and logged at debug.
Hermes turns must never break because the bridge can't reach NeMo-Flow.

Modeled on the bundled Langfuse plugin
(/home/mpenn/hermes-agent/plugins/observability/langfuse/__init__.py).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_PAYLOAD_BYTES = 262_144  # 256 KiB; oversize payloads drop body fields, keep correlation.

_LOCK = threading.Lock()
_CLIENT: Optional[Any] = None  # httpx.Client, lazily created
_GATEWAY_URL: Optional[str] = None
_GATEWAY_LOOKED_UP = False
_DISABLED_LOGGED = False


# ---------------------------------------------------------------------------
# Gateway URL + HTTP client
# ---------------------------------------------------------------------------

def _gateway_url() -> Optional[str]:
    global _GATEWAY_URL, _GATEWAY_LOOKED_UP, _DISABLED_LOGGED
    with _LOCK:
        if _GATEWAY_LOOKED_UP:
            return _GATEWAY_URL
        _GATEWAY_LOOKED_UP = True
        url = os.environ.get("NEMO_FLOW_GATEWAY_URL", "").strip()
        if not url:
            if not _DISABLED_LOGGED:
                logger.debug(
                    "nemo-flow-bridge: NEMO_FLOW_GATEWAY_URL is not set; "
                    "bridge will not forward hooks (expected when Hermes "
                    "runs outside `nemo-flow hermes -- ...`)."
                )
                _DISABLED_LOGGED = True
            return None
        _GATEWAY_URL = url.rstrip("/")
        return _GATEWAY_URL


def _client():
    global _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            import httpx  # type: ignore

            _CLIENT = httpx.Client(timeout=2.0)
            return _CLIENT
        except Exception as exc:  # pragma: no cover
            logger.debug("nemo-flow-bridge: failed to construct httpx client: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------

def _safe_jsonable(value: Any, _depth: int = 0) -> Any:
    """Recursively coerce any value into something json.dumps can serialize.
    Covers pydantic v2 SDK objects, older to_dict shapes, SimpleNamespace
    (vars(obj) → dict), and arbitrary attribute-bearing classes."""
    if _depth > 12:  # guard against pathological cycles
        return repr(value)[:256]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v, _depth + 1) for v in value]
    # Pydantic v2 (OpenAI/Anthropic SDK responses)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:
            try:
                return _safe_jsonable(dump(), _depth + 1)
            except Exception:
                pass
    # Older SDK shapes
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _safe_jsonable(to_dict(), _depth + 1)
        except Exception:
            pass
    # SimpleNamespace and attribute-bearing classes (Hermes' NormalizedResponse,
    # the v0.14.0 response wrapper, etc.)
    if isinstance(value, SimpleNamespace) or hasattr(value, "__dict__"):
        try:
            return _safe_jsonable(vars(value), _depth + 1)
        except Exception:
            pass
    return repr(value)[:4096]


def _coerce_request_messages(
    *,
    request_messages: Any = None,
    conversation_history: Any = None,
    user_message: Any = None,
) -> list:
    """Hermes v0.14.0 passes a real `request_messages` list of {role, content}
    dicts. Fall back to conversation_history, then synthesize a single user
    message from user_message — mirrors Langfuse's resolver at
    plugins/observability/langfuse/__init__.py:409."""
    for candidate in (request_messages, conversation_history):
        if isinstance(candidate, list) and candidate:
            return candidate
    if user_message:
        return [{"role": "user", "content": user_message}]
    if isinstance(request_messages, list):
        return request_messages
    return []


def _serialize_tool_calls(tool_calls: Any) -> list:
    if not tool_calls:
        return []
    out = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            out.append(_safe_jsonable(tc))
            continue
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) if fn else None
        args = getattr(fn, "arguments", None) if fn else None
        out.append({
            "id": getattr(tc, "id", None),
            "type": getattr(tc, "type", None) or "function",
            "function": {"name": name, "arguments": _safe_jsonable(args)},
        })
    return out


def _serialize_assistant_message(obj: Any) -> Optional[dict]:
    """Pull the fields NeMo-Flow's adapter inspects on
    `response.assistant_message` (adapters/hermes.rs:264-280)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return _safe_jsonable(obj)
    return {
        "content": _safe_jsonable(getattr(obj, "content", None)),
        "tool_calls": _serialize_tool_calls(getattr(obj, "tool_calls", None)),
        "reasoning": _safe_jsonable(getattr(obj, "reasoning", None)),
    }


def _serialize_response_object(response: Any) -> Optional[dict]:
    """Turn the v0.14.0 `response=` kwarg (a SimpleNamespace with
    .choices/.usage/.model/.id) into a dict. The result has `choices` at
    top-level, which adapters/hermes.rs:251-256 recognizes as a real
    provider response and uses to mark provider_payload_exact=true."""
    if response is None:
        return None
    blob = _safe_jsonable(response)
    if isinstance(blob, dict) and (
        "choices" in blob or "output" in blob or "content" in blob
    ):
        return blob
    return None


# ---------------------------------------------------------------------------
# Forwarder
# ---------------------------------------------------------------------------

def _cap_payload(payload: dict) -> dict:
    """If JSON-encoded payload exceeds 256 KiB, drop body fields but keep
    correlation keys. Adapter's truncation guard then degrades to lossy
    fallback rather than discarding the event."""
    try:
        encoded = json.dumps(payload, default=str)
    except Exception:
        return payload
    if len(encoded) <= _MAX_PAYLOAD_BYTES:
        return payload
    trimmed = dict(payload)
    request = trimmed.get("request")
    if isinstance(request, dict) and "body" in request:
        request = dict(request)
        request.pop("body", None)
        trimmed["request"] = request
    response = trimmed.get("response")
    if isinstance(response, dict):
        response = dict(response)
        response.pop("raw_response", None)
        response.pop("assistant_message", None)
        trimmed["response"] = response
    return trimmed


def _forward(payload: dict) -> None:
    url = _gateway_url()
    if not url:
        return
    client = _client()
    if client is None:
        return
    try:
        client.post(f"{url}/hooks/hermes", json=_cap_payload(payload))
    except Exception as exc:
        logger.debug("nemo-flow-bridge: forward to %s failed: %s", url, exc)


def _correlation(kwargs: dict) -> dict:
    """The fields NeMo-Flow's adapter uses to synthesize api_call_id and
    correlate hook events back to the right session/turn scope."""
    return {
        "task_id": kwargs.get("task_id"),
        "session_id": kwargs.get("session_id"),
        "api_call_count": kwargs.get("api_call_count"),
        "platform": kwargs.get("platform"),
        "model": kwargs.get("model"),
        "provider": kwargs.get("provider"),
        "base_url": kwargs.get("base_url"),
        "api_mode": kwargs.get("api_mode"),
    }


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------

def on_pre_api_request(**kwargs: Any) -> None:
    try:
        payload = _correlation(kwargs)
        payload["hook_event_name"] = "pre_api_request"
        messages = _coerce_request_messages(
            request_messages=kwargs.get("request_messages"),
            conversation_history=kwargs.get("conversation_history"),
            user_message=kwargs.get("user_message"),
        )
        payload["request"] = {
            "body": _safe_jsonable(messages),
            "model": kwargs.get("model"),
            "api_mode": kwargs.get("api_mode"),
            "max_tokens": kwargs.get("max_tokens"),
        }
        _forward(payload)
    except Exception as exc:
        logger.debug("nemo-flow-bridge: on_pre_api_request failed: %s", exc)


def on_post_api_request(**kwargs: Any) -> None:
    try:
        payload = _correlation(kwargs)
        payload["hook_event_name"] = "post_api_request"
        # Primary path: serialize the real response SimpleNamespace into a
        # dict with `choices/usage/model/id`. The adapter's
        # hermes_exact_response sees .choices and returns the whole dict,
        # which OpenInference renders as input/output.value.
        raw_response = _serialize_response_object(kwargs.get("response"))
        # Redundant fallback path: include serialized assistant_message in
        # case raw_response can't be extracted. Adapter has a separate
        # branch for response.assistant_message.{content,tool_calls}.
        assistant_message = _serialize_assistant_message(kwargs.get("assistant_message"))
        payload["response"] = {
            "raw_response": raw_response,
            "assistant_message": assistant_message,
            "model": kwargs.get("response_model") or kwargs.get("model"),
            "finish_reason": kwargs.get("finish_reason"),
            "api_duration": kwargs.get("api_duration"),
            "usage": _safe_jsonable(kwargs.get("usage")),
        }
        _forward(payload)
    except Exception as exc:
        logger.debug("nemo-flow-bridge: on_post_api_request failed: %s", exc)


# ---------------------------------------------------------------------------
# Plugin entry-point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Wire pre/post_api_request to the in-process forwarders.

    Shell-hook entries for these two events are intentionally removed from
    config.yaml (see generate-config.ts) so the gateway sees exactly one
    event per call — the enriched one from this plugin.
    """
    ctx.register_hook("pre_api_request", on_pre_api_request)
    ctx.register_hook("post_api_request", on_post_api_request)
