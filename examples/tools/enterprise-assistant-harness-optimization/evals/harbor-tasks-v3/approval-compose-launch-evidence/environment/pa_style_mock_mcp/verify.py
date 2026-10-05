"""Deterministic checks shared by eval runners and a future Gym adapter."""

from __future__ import annotations

from typing import Any


def verify_case(
    case: dict[str, Any],
    calls: list[dict[str, Any]],
    final_answer: str,
    outbox: list[dict[str, Any]],
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate trajectory, grounding, answer facts, and mutation state independently."""
    actual_tools = [call["name"] for call in calls]
    expected = case.get("expectations", {})
    failures: list[str] = []

    missing_tools = sorted(set(expected.get("required_tools", [])) - set(actual_tools))
    successful_tools = {
        result.get("name")
        for result in (tool_results or [])
        if result.get("ok") is True
    }
    required_successful_tools = expected.get("required_successful_tools", [])
    missing_successful_tools = sorted(set(required_successful_tools) - successful_tools)
    forbidden_tools = sorted(set(expected.get("forbidden_tools", [])) & set(actual_tools))
    missing_facts = [fact for fact in expected.get("required_facts", []) if fact.lower() not in final_answer.lower()]
    forbidden_claims = [claim for claim in expected.get("forbidden_claims", []) if claim.lower() in final_answer.lower()]

    if missing_tools:
        failures.append(f"missing required tools: {', '.join(missing_tools)}")
    if required_successful_tools and tool_results is None:
        failures.append("required successful tools cannot be verified: run has no replayed tool_results")
    elif missing_successful_tools:
        failures.append(f"missing successful tools: {', '.join(missing_successful_tools)}")
    if forbidden_tools:
        failures.append(f"used forbidden tools: {', '.join(forbidden_tools)}")
    if missing_facts:
        failures.append(f"missing answer facts: {', '.join(missing_facts)}")
    if forbidden_claims:
        failures.append(f"included forbidden claims: {', '.join(forbidden_claims)}")

    expected_outbox_count = expected.get("outbox_count")
    if expected_outbox_count is not None and len(outbox) != expected_outbox_count:
        failures.append(f"expected {expected_outbox_count} sent messages, found {len(outbox)}")

    for expected_message in expected.get("outbox_messages", []):
        if not _contains_message(outbox, expected_message):
            recipient = expected_message.get("recipient", "<unspecified>")
            failures.append(f"expected sent message not found for recipient: {recipient}")

    dimensions = {
        "trajectory": not missing_tools and not missing_successful_tools and not forbidden_tools and not (required_successful_tools and tool_results is None),
        "answer": not missing_facts and not forbidden_claims,
        "state": (
            (expected_outbox_count is None or len(outbox) == expected_outbox_count)
            and not any(failure.startswith("expected sent message") for failure in failures)
        ),
    }
    return {"passed": not failures, "failures": failures, "dimensions": dimensions}


def _contains_message(outbox: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    """Match exact routing fields and optional case-insensitive body evidence."""
    for message in outbox:
        if any(message.get(key) != value for key, value in expected.items() if key != "body_contains"):
            continue
        body_contains = expected.get("body_contains")
        if body_contains is None or body_contains.lower() in message.get("body", "").lower():
            return True
    return False
