"""Conservative extraction of this demo's real Hermes ATIF trajectories."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .tools import ToolRegistry

MCP_SERVER_PREFIXES = ("mcp__pa_style_enterprise__", "mcp__enterprise_world__")


def _atof_scope_pairs(
    events: Iterable[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for event in events:
        uuid = event.get("uuid")
        phase = event.get("scope_category")
        if event.get("kind") == "scope" and isinstance(uuid, str) and phase in {"start", "end"}:
            pairs[uuid][phase] = event
    return pairs


def atof_events_to_atif_trajectories(
    events: list[dict[str, Any]], *, redact_non_fixture_tools: bool = False
) -> list[dict[str, Any]]:
    """Normalize completed Hermes turn scopes into loss-recorded ATIF-v1.7.

    Relay 0.7.2 emits complete ATOF turn scopes for Hermes 0.20.6 but does not
    flush its configured ATIF sink. This adapter preserves recorded prompts,
    tool arguments/results, timestamps, model, and token counts. It records the
    structural losses instead of claiming native Relay ATIF provenance.
    """
    pairs = _atof_scope_pairs(events)
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("scope_category") == "start" and isinstance(event.get("parent_uuid"), str):
            children[event["parent_uuid"]].append(event)

    trajectories: list[dict[str, Any]] = []
    for turn_id, pair in pairs.items():
        turn_start = pair.get("start")
        turn_end = pair.get("end")
        if not turn_start or not turn_end or turn_start.get("name") != "hermes.turn":
            continue

        descendants: list[dict[str, Any]] = []
        pending = list(children.get(turn_id, []))
        while pending:
            event = pending.pop(0)
            descendants.append(event)
            if isinstance(event.get("uuid"), str):
                pending.extend(children.get(event["uuid"], []))

        prompt = ""
        final_answer = ""
        model_name: str | None = None
        prompt_tokens = completion_tokens = 0
        for event in descendants:
            if event.get("category") != "llm" or event.get("scope_category") != "start":
                continue
            request_data = event.get("data")
            request = request_data.get("content") if isinstance(request_data, dict) else None
            if isinstance(request, dict):
                for message in request.get("messages", []):
                    if message.get("role") == "user" and isinstance(message.get("content"), str):
                        prompt = message["content"]
            llm_end = pairs.get(event.get("uuid"), {}).get("end")
            response = llm_end.get("data") if llm_end else None
            if not isinstance(response, dict):
                continue
            if isinstance(response.get("model"), str):
                model_name = response["model"]
            usage = response.get("usage")
            if isinstance(usage, dict):
                prompt_tokens += int(usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0)
            for choice in response.get("choices", []):
                content = (choice.get("message") or {}).get("content")
                if isinstance(content, str) and content.strip():
                    final_answer = content

        steps: list[dict[str, Any]] = [
            {
                "step_id": 1,
                "timestamp": turn_start.get("timestamp"),
                "source": "user",
                "message": prompt,
            }
        ]
        for event in descendants:
            if event.get("category") != "tool" or event.get("scope_category") != "start":
                continue
            scope_id = event.get("uuid")
            terminal = pairs.get(scope_id, {}).get("end")
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
            call_id = metadata.get("tool_call_id") or scope_id
            tool_name = event.get("name")
            is_fixture_tool = isinstance(tool_name, str) and tool_name.startswith(
                MCP_SERVER_PREFIXES
            )
            arguments = event.get("data") if isinstance(event.get("data"), dict) else {}
            if redact_non_fixture_tools and not is_fixture_tool:
                arguments = {"redacted": "non-fixture tool input removed for public bundle"}
            step: dict[str, Any] = {
                "step_id": len(steps) + 1,
                "timestamp": event.get("timestamp"),
                "source": "agent",
                "message": "",
                "tool_calls": [
                    {
                        "tool_call_id": str(call_id),
                        "function_name": tool_name,
                        "arguments": arguments,
                    }
                ],
            }
            if terminal:
                content = terminal.get("data")
                if redact_non_fixture_tools and not is_fixture_tool:
                    content = "[redacted: non-fixture tool output removed for public bundle]"
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
                step["observation"] = {
                    "results": [{"source_call_id": str(call_id), "content": content}]
                }
            steps.append(step)
        steps.append(
            {
                "step_id": len(steps) + 1,
                "timestamp": turn_end.get("timestamp"),
                "source": "agent",
                "model_name": model_name,
                "message": final_answer,
            }
        )
        trajectories.append(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": turn_id,
                "trajectory_id": turn_id,
                "agent": {
                    "name": "Hermes-enterprise-world",
                    "version": "tutorial-baseline-v1",
                    "model_name": model_name,
                },
                "final_metrics": {
                    "total_prompt_tokens": prompt_tokens,
                    "total_completion_tokens": completion_tokens,
                    "total_steps": len(steps),
                },
                "extra": {
                    "turn_outcome": (
                        turn_end.get("data", {}).get("outcome")
                        if isinstance(turn_end.get("data"), dict)
                        else None
                    ),
                    "normalization": {
                        "source_format": "ATOF",
                        "source_turn_id": turn_id,
                        "uncertainties": [
                            "Hermes 0.20.6 emitted no session-end event, so Relay 0.7.2 did not flush native ATIF."
                        ],
                        "losses": [
                            "ATOF scope nesting is flattened into sequential ATIF agent steps.",
                            *(
                                [
                                    "Non-fixture tool inputs and outputs were removed at the public-data boundary."
                                ]
                                if redact_non_fixture_tools
                                else []
                            ),
                        ],
                    }
                },
                "steps": steps,
            }
        )
    return trajectories


def _sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def hermes_tool_name_map(catalog: str = "extended") -> dict[str, str]:
    """Map Hermes' provider-safe MCP names back to public mock tool names."""
    return {
        f"{prefix}{_sanitize(schema['name'])}": schema["name"]
        for schema in ToolRegistry(catalog=catalog).schemas()
        for prefix in MCP_SERVER_PREFIXES
    }


def extract_run(case_id: str, trajectory: dict[str, Any], catalog: str = "extended") -> dict[str, Any]:
    """Extract canonical calls and final answer, failing on unknown tool names.

    ATIF records tool calls on agent steps as ``function_name`` and arguments.
    State is reconstructed by replaying only the canonical mock-MCP calls in a
    fresh world; this lets the evaluator check approval-gated writes without
    trusting model prose.
    """
    if not str(trajectory.get("schema_version", "")).startswith("ATIF-v1"):
        raise ValueError("expected an ATIF-v1 trajectory")
    name_map = hermes_tool_name_map(catalog)
    calls: list[dict[str, Any]] = []
    final_answer = ""
    for step in trajectory.get("steps", []):
        for tool_call in step.get("tool_calls", []):
            raw_name = tool_call.get("function_name")
            name = name_map.get(raw_name)
            if name is None:
                raise ValueError(f"ATIF contains an unknown or non-demo tool: {raw_name!r}")
            arguments = tool_call.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise TypeError(f"arguments for {raw_name!r} are not an object")
            calls.append({"name": name, "arguments": arguments})
        message = step.get("message")
        if isinstance(message, str) and message.strip():
            final_answer = message

    registry = ToolRegistry(catalog=catalog)
    tool_results: list[dict[str, Any]] = []
    for call in calls:
        result = registry.call(call["name"], call["arguments"])
        tool_results.append(
            {
                "name": call["name"],
                "ok": bool(result.get("ok")),
                "error_code": result.get("error", {}).get("code") if not result.get("ok") else None,
            }
        )
    return {
        "case_id": case_id,
        "calls": calls,
        "tool_results": tool_results,
        "final_answer": final_answer,
        "outbox": registry.world.outbox,
        "source": {"atif_session_id": trajectory.get("session_id"), "atif_schema_version": trajectory["schema_version"]},
    }
