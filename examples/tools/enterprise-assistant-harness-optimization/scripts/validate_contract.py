#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate the checked-in fictional world and its seed-eval contract.

This is deliberately structural validation, not a trace generator. It prevents
fixture drift from silently invalidating the mock-MCP and future Gym adapters.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp import ToolRegistry


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def validate_world(world: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_collections = [
        "people",
        "mail_threads",
        "chat_threads",
        "calendar_events",
        "knowledge_documents",
        "files",
        "structured_files",
        "project_tasks",
        "analytics_metrics",
        "support_tickets",
    ]
    for collection in required_collections:
        if not isinstance(world.get(collection), list) or not world[collection]:
            errors.append(f"world requires a non-empty {collection} collection")

    if not isinstance(world.get("world_version"), str) or not world["world_version"]:
        errors.append("world requires a non-empty string world_version")
    if not isinstance(world.get("connector_status"), dict):
        errors.append("world requires connector_status object")

    known_people: set[str] = set()
    for person in world.get("people", []):
        if not all(isinstance(person.get(field), str) and person[field] for field in ("id", "name", "email", "team")):
            errors.append(f"person {person.get('id')!r} is missing a required string field")
            continue
        if not person["email"].endswith("@example.test"):
            errors.append(f"person {person['id']} must use an example.test email")
        known_people.add(person["email"])
    for thread in world.get("mail_threads", []):
        if not all(key in thread for key in ("id", "subject", "participants", "updated_at", "messages")):
            errors.append(f"mail thread {thread.get('id')} is missing required fields")
        unknown = set(thread.get("participants", [])) - known_people
        if unknown:
            errors.append(f"mail thread {thread.get('id')} has unknown participants: {sorted(unknown)}")
    for thread in world.get("chat_threads", []):
        if not all(key in thread for key in ("id", "channel", "updated_at", "messages")):
            errors.append(f"chat thread {thread.get('id')} is missing required fields")
    for event in world.get("calendar_events", []):
        if not all(key in event for key in ("id", "title", "starts_at", "attendees")):
            errors.append(f"calendar event {event.get('id')} is missing required fields")
        unknown = set(event.get("attendees", [])) - known_people
        if unknown:
            errors.append(f"calendar event {event.get('id')} has unknown attendees: {sorted(unknown)}")
    for file in world.get("files", []):
        if file.get("owner") not in known_people:
            errors.append(f"file {file.get('id')} has unknown owner")
    for file in world.get("structured_files", []):
        if file.get("owner") not in known_people:
            errors.append(f"structured file {file.get('id')} has unknown owner")
        if file.get("content_type") != "application/json" or not isinstance(file.get("content"), dict):
            errors.append(f"structured file {file.get('id')} must contain application/json object content")

    ids: list[str] = []
    for collection in required_collections:
        ids.extend(item.get("id", "") for item in world.get(collection, []))
    duplicates = sorted({identifier for identifier in ids if identifier and ids.count(identifier) > 1})
    if duplicates:
        errors.append(f"duplicate top-level fixture IDs: {duplicates}")

    return errors


def validate(world: dict[str, Any], cases: list[dict[str, Any]]) -> list[str]:
    errors = validate_world(world)

    schema_names = {
        schema["name"] for schema in ToolRegistry(catalog="extended").schemas()
    }
    case_ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in case_ids:
            errors.append(f"case ID missing or duplicated: {case_id!r}")
        case_ids.add(case_id)
        expected = case.get("expectations", {})
        for tool in expected.get("required_tools", []) + expected.get("required_successful_tools", []) + expected.get("forbidden_tools", []):
            if tool not in schema_names:
                errors.append(f"case {case_id} references unknown tool: {tool}")
        if "outbox_count" in expected and (not isinstance(expected["outbox_count"], int) or expected["outbox_count"] < 0):
            errors.append(f"case {case_id} has invalid outbox_count")
        for message in expected.get("outbox_messages", []):
            if not isinstance(message, dict) or "recipient" not in message:
                errors.append(f"case {case_id} has an invalid outbox_messages entry")
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures" / "world-v2.json")
    parser.add_argument("--cases", type=Path, default=ROOT / "tests" / "fixtures" / "world-contract-cases.json")
    parser.add_argument("--skip-eval", action="store_true", help="Validate only a candidate fixture's structural contract")
    args = parser.parse_args()
    world = load(args.fixture)
    cases = [] if args.skip_eval else load(args.cases)
    errors = validate_world(world) if args.skip_eval else validate(world, cases)
    if errors:
        print("Contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Contract validation passed: world={world['world_version']}, seed_cases={len(cases)}, "
        f"focused_tools={len(ToolRegistry(catalog='focused').schemas())}, "
        f"extended_tools={len(ToolRegistry(catalog='extended').schemas())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
