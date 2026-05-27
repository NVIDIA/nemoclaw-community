# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""In-process Hermes plugin that forwards pre/post_api_request and
pre/post_tool_call hooks to the NeMo-Relay sidecar at
`${NEMO_RELAY_GATEWAY_URL}/hooks/hermes` with the real request/response
bodies attached. Wrapping the body as `{messages, model, max_tokens}`
and synthesizing stable tool_call_ids are workarounds — see the inline
comments at each call site for the upstream rationale.

Fail-open: exceptions are logged at debug; Hermes turns must never break
because the bridge can't reach NeMo-Relay. Modeled on Hermes's bundled
Langfuse observability plugin.

TODO(upstream): this whole plugin is retirable when
https://github.com/NousResearch/hermes-agent/pull/29724 lands a built-in
NeMo-Flow telemetry plugin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import deque
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CLIENT: Optional[Any] = None  # httpx.Client, lazily created
_GATEWAY_URL: Optional[str] = None
_GATEWAY_LOOKED_UP = False
_DISABLED_LOGGED = False

# FIFO of synthesized tool_call_ids keyed by (task_id, tool_name). The key
# uses task_id (not session_id) because Hermes' pre/post call sites are
# asymmetric: agent_runtime_helpers.py fires pre_tool_call without
# passing session_id (defaults to ""), while model_tools.py fires
# post_tool_call with the real session_id. task_id and tool_name are passed
# consistently to both, so they form a stable join key. post_tool_call pops
# from the matching queue to pair with the right pre.
#
# Each bucket is a bounded deque so a stream of pre_tool_call events
# without matching post_tool_call (tool blocked, agent crash mid-turn,
# post handler exception) can't grow without bound. 512 entries is far
# more than any realistic single turn produces (single-digit tool calls)
# but leaves generous safety margin before the oldest unmatched pre is
# evicted. Empty buckets are deleted on pop so the outer dict tracks only
# currently-pending pairs.
_PENDING_MAX_PER_KEY = 512
_PENDING_PRE: dict[tuple[str, str], deque[str]] = {}
_PENDING_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Gateway URL + HTTP client
# ---------------------------------------------------------------------------

def _gateway_url() -> Optional[str]:
    global _GATEWAY_URL, _GATEWAY_LOOKED_UP, _DISABLED_LOGGED
    with _LOCK:
        if _GATEWAY_LOOKED_UP:
            return _GATEWAY_URL
        _GATEWAY_LOOKED_UP = True
        url = os.environ.get("NEMO_RELAY_GATEWAY_URL", "").strip()
        if not url:
            if not _DISABLED_LOGGED:
                logger.debug(
                    "nemo-relay: NEMO_RELAY_GATEWAY_URL is not set; "
                    "bridge will not forward hooks. start.sh exports this "
                    "for PID-1 hermes and interactive shells — a missing "
                    "value in either context indicates a misconfiguration."
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
            logger.debug("nemo-relay: failed to construct httpx client: %s", exc)
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
    plugins/observability/langfuse/__init__.py."""
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
    """Pull the fields NeMo-Relay's adapter inspects on
    `response.assistant_message` (adapters/hermes.rs)."""
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
    top-level, which adapters/hermes.rs recognizes as a real
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

def _forward(payload: dict) -> None:
    url = _gateway_url()
    if not url:
        return
    client = _client()
    if client is None:
        return
    try:
        client.post(f"{url}/hooks/hermes", json=payload)
    except Exception as exc:
        logger.debug("nemo-relay: forward to %s failed: %s", url, exc)


def _correlation(kwargs: dict) -> dict:
    """The fields NeMo-Relay's adapter uses to synthesize api_call_id and
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


def _stable_tool_call_id(
    *,
    task_id: str,
    tool_name: str,
    args: Any,
    supplied: Any,
) -> str:
    """Return supplied tool_call_id if non-empty; otherwise synthesize a stable
    id from (task_id, tool_name, args) so pre and post produce the same id
    and the gateway pairs them into a single Phoenix span.

    task_id (not session_id) is in the digest because Hermes' pre call site
    at agent_runtime_helpers.py doesn't pass session_id (defaults
    to ""), while the post call site at model_tools.py does — so
    including session_id would make pre's hash differ from post's. task_id
    is passed to both call sites and is unique per turn.
    """
    if isinstance(supplied, str) and supplied.strip():
        return supplied
    try:
        args_blob = json.dumps(_safe_jsonable(args), sort_keys=True, default=str)
    except Exception:
        args_blob = repr(args)[:1024]
    digest = hashlib.sha1(
        f"{task_id}|{tool_name}|{args_blob}".encode("utf-8")
    ).hexdigest()[:16]
    return f"nfb-{digest}"


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
        # Wrap as {"messages": [...], "model": ..., ...} to match NeMo-Relay's
        # documented LlmRequest.content convention
        # (docs/integrate-frameworks/wrap-llm-calls.md, asserted by
        # crates/core/tests/unit/observability/openinference_tests.rs). With
        # this shape, openinference.rs:llm_input_display_value finds the
        # messages list via content.get("messages") and renders each as
        # "role: content", so Phoenix's input.value carries the full prompt
        # rather than a lossy "Requested tools: ..." summary. ATIF's
        # unwrap_llm_request surfaces the same dict at
        # step.extra.llm_request, matching the documented shape.
        payload["request"] = {
            "body": {
                "messages": _safe_jsonable(messages),
                "model": kwargs.get("model"),
                "max_tokens": kwargs.get("max_tokens"),
            },
            "api_mode": kwargs.get("api_mode"),
        }
        _forward(payload)
    except Exception as exc:
        logger.debug("nemo-relay: on_pre_api_request failed: %s", exc)


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
        logger.debug("nemo-relay: on_post_api_request failed: %s", exc)


def on_pre_tool_call(**kwargs: Any) -> None:
    try:
        task_id = kwargs.get("task_id") or ""
        tool_name = kwargs.get("tool_name") or ""
        args = kwargs.get("args")
        tcid = _stable_tool_call_id(
            task_id=task_id,
            tool_name=tool_name,
            args=args,
            supplied=kwargs.get("tool_call_id"),
        )
        with _PENDING_LOCK:
            bucket = _PENDING_PRE.get((task_id, tool_name))
            if bucket is None:
                bucket = deque(maxlen=_PENDING_MAX_PER_KEY)
                _PENDING_PRE[(task_id, tool_name)] = bucket
            bucket.append(tcid)
        payload = _correlation(kwargs)
        payload["hook_event_name"] = "pre_tool_call"
        payload["tool_name"] = tool_name
        payload["args"] = _safe_jsonable(args)
        payload["tool_call_id"] = tcid
        _forward(payload)
    except Exception as exc:
        logger.debug("nemo-relay: on_pre_tool_call failed: %s", exc)


def on_post_tool_call(**kwargs: Any) -> None:
    try:
        task_id = kwargs.get("task_id") or ""
        tool_name = kwargs.get("tool_name") or ""
        args = kwargs.get("args")
        # Hermes' tool-dispatch path fires pre_tool_call with tool_call_id=""
        # (agent_runtime_helpers.py calls
        # get_pre_tool_call_block_message without passing tool_call_id or
        # session_id) and post_tool_call with the real provider id and the
        # real session_id (model_tools.py). The pre already shipped a
        # synthesized id to the gateway; we must echo the SAME id at post or
        # the gateway adapter treats them as two unpaired spans. FIFO key is
        # (task_id, tool_name) since those two are the only fields passed
        # consistently to both call sites. FIFO-pop first; fall back to the
        # supplied id only if the FIFO is empty (e.g. a post without a
        # matching pre, which would happen if we missed the pre event during
        # startup).
        with _PENDING_LOCK:
            bucket = _PENDING_PRE.get((task_id, tool_name))
            popped = bucket.popleft() if bucket else None
            if bucket is not None and not bucket:
                del _PENDING_PRE[(task_id, tool_name)]
        if popped is not None:
            tcid = popped
        else:
            tcid = _stable_tool_call_id(
                task_id=task_id,
                tool_name=tool_name,
                args=args,
                supplied=kwargs.get("tool_call_id"),
            )
        payload = _correlation(kwargs)
        payload["hook_event_name"] = "post_tool_call"
        payload["tool_name"] = tool_name
        payload["args"] = _safe_jsonable(args)
        payload["result"] = _safe_jsonable(kwargs.get("result"))
        payload["duration_ms"] = kwargs.get("duration_ms")
        payload["tool_call_id"] = tcid
        _forward(payload)
    except Exception as exc:
        logger.debug("nemo-relay: on_post_tool_call failed: %s", exc)


# ---------------------------------------------------------------------------
# Plugin entry-point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Wire pre/post_api_request and pre/post_tool_call to the in-process
    forwarders.

    Shell-hook entries for these four events are intentionally removed from
    config.yaml (see generate-config.ts) so the gateway sees exactly one
    event per call — the enriched one from this plugin. For tool calls the
    plugin also guarantees a stable tool_call_id, which Hermes' defensive
    `tool_call_id or ""` would otherwise strip, causing the gateway adapter
    to synthesize a fresh UUID per call and emit two unpaired spans.
    """
    ctx.register_hook("pre_api_request", on_pre_api_request)
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
