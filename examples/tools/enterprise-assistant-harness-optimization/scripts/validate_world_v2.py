#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate world-v2 scale and the fidelity properties used by its evals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pa_style_mock_mcp import EnterpriseWorld, ToolRegistry
from scripts.validate_contract import validate_world

MINIMUM_COUNTS = {
    "people": 50,
    "mail_threads": 50,
    "chat_threads": 50,
    "calendar_events": 30,
    "knowledge_documents": 30,
    "files": 30,
    "structured_files": 20,
    "project_tasks": 40,
    "analytics_metrics": 30,
    "support_tickets": 40,
}


def validate(path: Path) -> tuple[list[str], dict[str, Any]]:
    world = json.loads(path.read_text())
    errors = validate_world(world)
    if world.get("world_version") != "v2":
        errors.append("world_version must be v2")
    counts = {name: len(world.get(name, [])) for name in MINIMUM_COUNTS}
    for name, minimum in MINIMUM_COUNTS.items():
        if counts[name] < minimum:
            errors.append(f"{name} needs at least {minimum} records, found {counts[name]}")

    registry = ToolRegistry(EnterpriseWorld.from_path(path), catalog="extended")
    ambiguous_people = registry.call(
        "people.search", {"query": "Jordan Lee", "page_size": 10}
    )
    if ambiguous_people.get("pagination", {}).get("total_items", 0) < 3:
        errors.append("directory must contain at least three Jordan Lee matches")

    file_page_one = registry.call(
        "files.search", {"query": "launch evidence register", "page": 1, "page_size": 5}
    )
    file_page_two = registry.call(
        "files.search", {"query": "launch evidence register", "page": 2, "page_size": 5}
    )
    target = "json_launch_evidence_register"
    if file_page_one.get("pagination", {}).get("total_items", 0) < 20:
        errors.append("launch evidence search must have at least 20 plausible matches")
    if target in {item["id"] for item in file_page_one.get("items", [])}:
        errors.append("target launch register must be outside a five-item first page")
    if target not in {item["id"] for item in file_page_two.get("items", [])}:
        errors.append("target launch register must be reproducibly present on page two")

    root_read = registry.call("files.read_json", {"file_id": target})
    bounded_read = registry.call(
        "files.read_json",
        {"file_id": target, "json_pointer": "/appendix", "max_items": 3},
    )
    security_read = registry.call(
        "files.read_json", {"file_id": target, "json_pointer": "/evidence/security"}
    )
    if "content" in root_read or "appendix" not in root_read.get("keys", []):
        errors.append("root JSON read must return an index that includes appendix, not content")
    if len(bounded_read.get("items", [])) != 3 or bounded_read.get("truncated") is not True:
        errors.append("large appendix must be bounded and report truncation")
    security = {item["key"]: item["value"] for item in security_read.get("items", [])}
    if security.get("status") != "missing" or security.get("owner") != "ava.patel@example.test":
        errors.append("canonical Security evidence anchor changed")

    chat = registry.call("chat.read_thread", {"thread_id": "chat_launch_blocker"})
    chat_text = json.dumps(chat).lower()
    if "security evidence packet" not in chat_text or "one business day" not in chat_text:
        errors.append("canonical chat evidence anchor changed")
    calendar = registry.call(
        "calendar.list_events", {"query": "launch readiness review", "page_size": 10}
    )
    canonical_event = next(
        (item for item in calendar.get("items", []) if item.get("id") == "cal_launch_review"),
        None,
    )
    if canonical_event is None or not canonical_event["starts_at"].startswith("2026-09-02"):
        errors.append("canonical readiness review must remain discoverable on the first page")

    first_fault = registry.call("chat.search", {"query": "network incident"})
    second_fault = registry.call("chat.search", {"query": "network incident"})
    if first_fault.get("error", {}).get("code") != "TEMPORARY_UNAVAILABLE" or not second_fault.get("ok"):
        errors.append("one-shot chat failure is not deterministic")
    if registry.call("connectors.get_status", {"connector": "crm"}).get("status") != "needs_auth":
        errors.append("CRM needs_auth anchor changed")

    register = next(
        item for item in world.get("structured_files", []) if item.get("id") == target
    )
    register_bytes = len(json.dumps(register, separators=(",", ":")).encode())
    if register_bytes < 30_000:
        errors.append(f"launch evidence register must exceed 30000 bytes, found {register_bytes}")

    stats = {
        "world_version": world.get("world_version"),
        "counts": counts,
        "jordan_lee_matches": ambiguous_people.get("pagination", {}).get("total_items"),
        "launch_register_matches": file_page_one.get("pagination", {}).get("total_items"),
        "launch_register_target_page_at_five": 2,
        "launch_register_bytes": register_bytes,
    }
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=ROOT / "fixtures" / "world-v2.json")
    args = parser.parse_args()
    errors, stats = validate(args.fixture)
    if errors:
        print("world-v2 validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
