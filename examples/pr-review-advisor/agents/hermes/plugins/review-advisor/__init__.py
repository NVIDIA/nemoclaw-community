# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Hermes registration for the stateful, read-only PR review advisor."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

from .runtime import (
    BASIS_KINDS,
    CATEGORIES,
    LESSON_KINDS,
    SEVERITIES,
    SIDES,
    SIMPLIFICATION_TAGS,
    STAGES,
    ReviewError,
    ReviewRuntime,
    json_tool_result,
)

_LOCK = threading.Lock()
_RUNTIMES: "OrderedDict[str, ReviewRuntime]" = OrderedDict()
_MAX_SESSIONS = 64


def _object(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _string(*, description: str = "", enum: tuple[str, ...] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "minLength": 1}
    if description:
        result["description"] = description
    if enum is not None:
        result["enum"] = list(enum)
    return result


_EVIDENCE = {"type": "array", "items": _string(), "minItems": 1, "maxItems": 100}
_SIMPLIFICATION = _object(
    {
        "tag": _string(enum=SIMPLIFICATION_TAGS),
        "cut": _string(),
        "replacement": _string(),
        "estimated_net_lines": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
        },
        "safety_boundary": _string(),
    }
)
_BASIS = _object(
    {
        "kind": _string(enum=BASIS_KINDS),
        "observed": _string(),
        "expected": _string(),
    }
)
_FINDING_FIELDS = {
    "severity": _string(enum=SEVERITIES),
    "category": _string(enum=CATEGORIES),
    "file": _string(description="Canonical checkout-relative POSIX path."),
    "line": {"type": "integer", "minimum": 1},
    "side": _string(
        description=(
            "Use head for a current checkout line, or base for an actual deleted "
            "old-side line in the trusted patch."
        ),
        enum=SIDES,
    ),
    "title": _string(),
    "description": _string(),
    "impact": _string(),
    "recommendation": _string(),
    "verification_hint": _string(),
    "missing_regression_test": _string(),
}
_ADDITION = _object(
    {
        **_FINDING_FIELDS,
        "evidence": _EVIDENCE,
        "basis": _BASIS,
        "simplification": _SIMPLIFICATION,
    },
    required=[*_FINDING_FIELDS, "evidence", "basis"],
)
_PATCH = _object(
    {**_FINDING_FIELDS, "simplification": _SIMPLIFICATION},
    required=[],
)
_UPDATE = _object(
    {
        "id": _string(),
        "patch": _PATCH,
        "reason": _string(),
        "evidence": _EVIDENCE,
    }
)
_RESOLUTION = _object(
    {
        "id": _string(),
        "reason": _string(),
        "evidence": _EVIDENCE,
    }
)
_SUPERSESSION = _object(
    {
        "id": _string(),
        "superseded_by": _string(),
        "reason": _string(),
        "evidence": _EVIDENCE,
    }
)

_TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    "review_begin": _object({}, required=[]),
    "review_status": _object({}, required=[]),
    "review_repo_read": _object(
        {
            "path": _string(description="Canonical checkout-relative regular file path."),
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        required=["path"],
    ),
    "review_repo_list": _object(
        {"path": _string(description="Canonical checkout-relative directory, or '.'.")},
        required=[],
    ),
    "review_repo_search": _object(
        {
            "query": _string(description="Literal text to find."),
            "path": _string(description="Canonical checkout-relative directory, or '.'."),
            "case_sensitive": {"type": "boolean"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        required=["query"],
    ),
    "review_diff": _object(
        {
            "path": _string(description="A path from review_begin.changed_files."),
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        required=["path"],
    ),
    "review_commit_stage": _object(
        {
            "stage": _string(enum=STAGES),
            "summary": _string(description="What this stage established."),
            "evidence": _EVIDENCE,
            "additions": {
                "type": "array",
                "items": _ADDITION,
                "maxItems": 100,
            },
            "updates": {
                "type": "array",
                "items": _UPDATE,
                "maxItems": 100,
            },
            "resolutions": {
                "type": "array",
                "items": _RESOLUTION,
                "maxItems": 100,
            },
            "supersessions": {
                "type": "array",
                "items": _SUPERSESSION,
                "maxItems": 100,
            },
            "no_changes_reason": {
                "anyOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "null"},
                ]
            },
        }
    ),
    "review_finalize": _object(
        {
            "one_line": _string(),
            "confidence": _string(enum=("low", "medium", "high")),
            "positives": {
                "type": "array",
                "items": _string(),
                "maxItems": 100,
            },
            "limitations": {
                "type": "array",
                "maxItems": 100,
                "items": _object(
                    {
                        "description": _string(),
                        "requires_human_review": {"type": "boolean"},
                    }
                ),
            },
            "lesson_candidates": {
                "type": "array",
                "maxItems": 20,
                "items": _object(
                    {
                        "kind": _string(enum=LESSON_KINDS),
                        "statement": _string(),
                        "rationale": _string(),
                        "evidence": _EVIDENCE,
                        "paths": {
                            "type": "array",
                            "items": _string(),
                            "maxItems": 100,
                        },
                        "finding_ids": {
                            "type": "array",
                            "items": _string(),
                            "maxItems": 100,
                        },
                    }
                ),
            },
        }
    ),
}

_DESCRIPTIONS = {
    "review_begin": (
        "Bind this Hermes session directly to the trusted exact base/head/profile and return "
        "the complete changed-file inventory plus validated repository profile."
    ),
    "review_status": "Read stage and canonical finding-ledger state.",
    "review_repo_read": (
        "Read bounded numbered lines from a regular checkout file. Repository symlinks "
        "and path escapes are refused."
    ),
    "review_repo_list": (
        "List one checkout directory without following repository symlinks."
    ),
    "review_repo_search": (
        "Search bounded regular checkout files for literal text without following symlinks."
    ),
    "review_diff": (
        "Read bounded numbered lines from the trusted host-generated patch for one changed file."
    ),
    "review_commit_stage": (
        "Atomically commit the next ordered review stage and its canonical ledger mutation. "
        "A rejected call changes no state."
    ),
    "review_finalize": (
        "After complete patch coverage and all six stages, produce the HMAC-attested "
        "normalized review artifact and untrusted lesson candidates. This tool never "
        "publishes or writes memory."
    ),
}


def _session_key(kwargs: dict[str, Any]) -> str:
    session_id = kwargs.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ReviewError("Hermes session_id is required for review state isolation")
    return session_id.strip()


def _runtime(kwargs: dict[str, Any]) -> ReviewRuntime:
    key = _session_key(kwargs)
    with _LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is not None:
            _RUNTIMES.move_to_end(key)
            return runtime
        runtime = ReviewRuntime.from_env()
        _RUNTIMES[key] = runtime
        while len(_RUNTIMES) > _MAX_SESSIONS:
            _RUNTIMES.popitem(last=False)
        return runtime


def _coerce_input(tool_input: Any) -> Any:
    if isinstance(tool_input, str):
        try:
            return json.loads(tool_input)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"tool input is not valid JSON: {exc}") from exc
    return tool_input


def _handler(name: str):
    def handle(tool_input: Any, **kwargs: Any) -> str:
        try:
            runtime = _runtime(kwargs)
            return json_tool_result(runtime, name, _coerce_input(tool_input))
        except ReviewError as exc:
            return json.dumps(
                {"ok": False, "error": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            )

    return handle


def _clear_session(**kwargs: Any) -> None:
    session_id = kwargs.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return
    with _LOCK:
        _RUNTIMES.pop(session_id.strip(), None)


def register(ctx: Any) -> None:
    """Register the isolated review tools with Hermes."""

    for name, parameters in _TOOL_PARAMETERS.items():
        ctx.register_tool(
            name=name,
            toolset="review-advisor",
            schema={
                "name": name,
                "description": _DESCRIPTIONS[name],
                "parameters": parameters,
            },
            handler=_handler(name),
            description=_DESCRIPTIONS[name],
        )
    ctx.register_hook("on_session_start", _clear_session)
    ctx.register_hook("on_session_end", _clear_session)
