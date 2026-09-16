#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate and summarize a NeMo Relay ATOF JSONL event stream."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

Event = dict[str, Any]
TOKEN_SUMMARY_FIELDS = {
    "llm_scopes_with_usage",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
}


def load_events(path: Path) -> list[Event]:
    events: list[Event] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(event, dict):
                raise TypeError(f"{path}:{line_number}: expected a JSON object")
            events.append(event)
    if not events:
        raise ValueError(f"{path}: no ATOF events found")
    return events


def metadata(event: Event) -> dict[str, Any]:
    value = event.get("metadata")
    return value if isinstance(value, dict) else {}


def is_scope(event: Event, category: str, phase: str) -> bool:
    return (
        event.get("kind") == "scope"
        and event.get("category") == category
        and event.get("scope_category") == phase
    )


def is_error_status(event: Event) -> bool:
    for key in ("otel.status_code", "status"):
        status = metadata(event).get(key)
        if status is not None and str(status).strip().upper() not in {"OK", "SUCCESS", "UNSET"}:
            return True
    # Relay's status describes callback completion. Hermes tools can instead
    # return a failure as an object or a JSON-encoded result string.
    result = event.get("data")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return False
    if not isinstance(result, dict):
        return False
    if result_reports_error(result):
        return True
    # web_extract returns one result per URL, including per-page failures.
    pages = result.get("results")
    return event.get("name") == "web_extract" and isinstance(pages, list) and any(
        isinstance(page, dict) and result_reports_error(page) for page in pages
    )


def result_reports_error(result: dict[str, Any]) -> bool:
    if result.get("error") or result.get("is_error") is True or result.get("success") is False:
        return True
    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return True
    return str(result.get("status", "")).strip().lower() in {
        "error", "failed", "timeout", "timed_out", "blocked", "denied", "cancelled", "degraded",
    }


def token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def usage_from_event(event: Event) -> dict[str, int] | None:
    data = event.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("usage"), dict):
        return None

    usage = data["usage"]
    prompt_tokens = token_count(usage.get("prompt_tokens"))
    completion_tokens = token_count(usage.get("completion_tokens"))
    total_tokens = token_count(usage.get("total_tokens"))
    if total_tokens is None and (
        prompt_tokens is not None or completion_tokens is not None
    ):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    if total_tokens is None:
        return None
    return {
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "total_tokens": total_tokens,
    }


def completed_llm_usage(events: list[Event]) -> list[dict[str, int]]:
    completed_scope_ids = {
        event.get("uuid")
        for event in events
        if is_scope(event, "llm", "end") and event.get("uuid") is not None
    }
    usage_by_scope: dict[Any, dict[str, int]] = {}

    for event in events:
        if event.get("kind") != "mark" or event.get("name") != "llm.chunk":
            continue
        scope_id = event.get("parent_uuid")
        usage = usage_from_event(event)
        if scope_id in completed_scope_ids and usage is not None:
            usage_by_scope[scope_id] = usage

    for event in events:
        if not is_scope(event, "llm", "end"):
            continue
        scope_id = event.get("uuid")
        usage = usage_from_event(event)
        if scope_id in completed_scope_ids and usage is not None:
            usage_by_scope[scope_id] = usage

    return list(usage_by_scope.values())


def summarize(events: list[Event]) -> dict[str, int]:
    tool_ends = [event for event in events if is_scope(event, "tool", "end")]
    llm_usage = completed_llm_usage(events)
    return {
        "events": len(events),
        "completed_llm_scopes": sum(is_scope(event, "llm", "end") for event in events),
        "llm_scopes_with_usage": len(llm_usage),
        "prompt_tokens": sum(usage["prompt_tokens"] for usage in llm_usage),
        "completion_tokens": sum(usage["completion_tokens"] for usage in llm_usage),
        "total_tokens": sum(usage["total_tokens"] for usage in llm_usage),
        "tool_calls": sum(is_scope(event, "tool", "start") for event in events),
        "tool_errors": sum(is_error_status(event) for event in tool_ends),
        "correlated_events": sum(event.get("uuid") is not None for event in events),
    }


def successful_tool_start_events(events: list[Event]) -> list[Event]:
    successful_uuids = {
        event.get("uuid")
        for event in events
        if is_scope(event, "tool", "end")
        and event.get("uuid") is not None
        and not is_error_status(event)
    }
    return [
        event
        for event in events
        if is_scope(event, "tool", "start") and event.get("uuid") in successful_uuids
    ]


def has_successful_tool_command(events: list[Event], required_command: str) -> bool:
    for event in successful_tool_start_events(events):
        data = event.get("data")
        if isinstance(data, dict) and isinstance(data.get("command"), str):
            if required_command in data["command"]:
                return True
    return False


def has_successful_tool_name(events: list[Event], required_name: str) -> bool:
    return any(
        event.get("name") == required_name
        for event in successful_tool_start_events(events)
    )


def validate_trace_requirements(
    events: list[Event],
    summary: dict[str, int],
    *,
    require_llm: bool,
    require_tool: bool,
    require_no_tool_errors: bool,
    required_tool_command: str | None,
    required_tool_names: list[str],
    require_token_usage: bool = False,
) -> None:
    missing: list[str] = []
    if require_llm and summary["completed_llm_scopes"] == 0:
        missing.append("completed LLM scope")
    if require_tool and summary["tool_calls"] == 0:
        missing.append("tool call")
    if require_no_tool_errors and summary["tool_errors"] != 0:
        missing.append("error-free tool calls")
    if require_token_usage and summary.get("total_tokens", 0) <= 0:
        missing.append("positive LLM token usage")
    if required_tool_command and not has_successful_tool_command(
        events, required_tool_command
    ):
        missing.append(f"successful tool command containing {required_tool_command!r}")
    for required_tool_name in required_tool_names:
        if not has_successful_tool_name(events, required_tool_name):
            missing.append(f"successful tool named {required_tool_name!r}")
    if missing:
        raise ValueError(f"trace does not meet tutorial requirements: {', '.join(missing)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a Relay ATOF JSONL trace.")
    parser.add_argument("trace", type=Path, help="Path to an ATOF JSONL trace")
    parser.add_argument(
        "--require-completed-llm-scope",
        action="store_true",
        help="Fail when the trace has no completed LLM scope",
    )
    parser.add_argument(
        "--require-token-usage",
        action="store_true",
        help="Fail when completed LLM scopes contain no positive token usage",
    )
    parser.add_argument(
        "--require-tool-call",
        action="store_true",
        help="Fail when the trace has no tool-call scope",
    )
    parser.add_argument(
        "--require-no-tool-errors",
        action="store_true",
        help="Fail when any tool-call scope ends with an error",
    )
    parser.add_argument(
        "--require-tool-command",
        help="Fail when no successfully completed tool call contains this command text",
    )
    parser.add_argument(
        "--require-tool-name",
        action="append",
        default=[],
        help="Fail when no successfully completed tool call has this name",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        events = load_events(args.trace)
        summary = summarize(events)
        validate_trace_requirements(
            events,
            summary,
            require_llm=args.require_completed_llm_scope,
            require_tool=args.require_tool_call,
            require_no_tool_errors=args.require_no_tool_errors,
            required_tool_command=args.require_tool_command,
            required_tool_names=args.require_tool_name,
            require_token_usage=args.require_token_usage,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"trace: {args.trace}")
    for label, value in summary.items():
        if label in TOKEN_SUMMARY_FIELDS and not args.require_token_usage:
            continue
        print(f"{label.replace('_', ' ')}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
