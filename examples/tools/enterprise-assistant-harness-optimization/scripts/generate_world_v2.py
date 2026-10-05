#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Expand world-v1 into a deterministic, reviewable enterprise-scale fixture."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "fixtures" / "world-v1.json"
DEFAULT_OUTPUT = ROOT / "fixtures" / "world-v2.json"

PROJECTS = [
    "Atlas", "Beacon", "Cedar", "Delta", "Ember", "Fjord", "Grove", "Harbor",
    "Ion", "Juniper", "Keystone", "Lumen", "Mesa", "Nimbus", "Orchid", "Pioneer",
]
FIRST_NAMES = [
    "Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Gray", "Harper",
    "Indigo", "Jordan", "Kai", "Logan", "Morgan", "Noor", "Parker", "Quinn",
]
LAST_NAMES = ["Brooks", "Diaz", "Evans", "Foster", "Gupta", "Hayes", "Ito", "Lee"]
TEAMS = ["Platform", "Security", "Sales", "Finance", "Product", "Support", "Data", "IT"]


def timestamp(index: int, *, hour: int = 8) -> str:
    value = datetime(2026, 7, 1, hour, tzinfo=timezone.utc) + timedelta(
        days=index % 58, hours=index % 9
    )
    return value.isoformat().replace("+00:00", "Z")


def place_anchors(
    generated: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    positions: list[int],
) -> list[dict[str, Any]]:
    result = generated[:]
    if len(positions) != len(anchors):
        raise ValueError("every anchor needs an insertion position")
    for position, anchor in sorted(zip(positions, anchors)):
        result.insert(min(position, len(result)), copy.deepcopy(anchor))
    return result


def generated_people(count: int) -> list[dict[str, str]]:
    result = []
    for index in range(count):
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)]
        result.append(
            {
                "id": f"person_{index + 1000:04d}",
                "name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}.{index:03d}@example.test",
                "team": TEAMS[index % len(TEAMS)],
            }
        )
    # Deliberate display-name ambiguity for directory tasks.
    result[9].update(
        name="Jordan Lee", email="jordan.lee.security@example.test", team="Security"
    )
    result[41].update(
        name="Jordan Lee", email="jordan.lee.sales@example.test", team="Sales"
    )
    result[57].update(
        name="Jordan Lee", email="jordan.lee.product@example.test", team="Product"
    )
    return result


def generated_mail(count: int, people: list[dict[str, str]]) -> list[dict[str, Any]]:
    subjects = [
        "Archived {project} launch blocker review",
        "{project} security evidence checklist",
        "{project} readiness review notes",
        "Quarterly budget planning for {project}",
        "Launch communications for {project}",
    ]
    result = []
    for index in range(count):
        project = PROJECTS[index % len(PROJECTS)]
        sender = people[index % len(people)]["email"]
        recipient = people[(index + 11) % len(people)]["email"]
        subject = subjects[index % len(subjects)].format(project=project)
        body = (
            f"Historical {project} record {index:03d}. The referenced review item was "
            f"closed before the current Q3 launch; confirm current status elsewhere."
        )
        result.append(
            {
                "id": f"mail_{project.lower()}_{index:03d}",
                "subject": subject,
                "participants": [sender, recipient],
                "updated_at": timestamp(index),
                "messages": [
                    {
                        "id": f"mail_{project.lower()}_{index:03d}_message_00",
                        "author": sender,
                        "body": body,
                    }
                ],
            }
        )
    return result


def generated_chat(count: int, people: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for index in range(count):
        project = PROJECTS[index % len(PROJECTS)]
        author = people[(index * 3) % len(people)]["email"]
        if index % 3 == 0:
            body = (
                f"Archived {project} launch blocker discussion: the old compliance checklist "
                "was resolved. This is not the current Q3 launch status."
            )
        elif index % 3 == 1:
            body = (
                f"The {project} team is reviewing a security evidence checklist for a different "
                "release. No decision is recorded here."
            )
        else:
            body = f"Social planning for the {project} launch event; no readiness decision."
        result.append(
            {
                "id": f"chat_{project.lower()}_{index:03d}",
                "channel": f"proj-{project.lower()}-{index % 4}",
                "updated_at": timestamp(index, hour=10),
                "messages": [
                    {
                        "id": f"chat_{project.lower()}_{index:03d}_message_00",
                        "author": author,
                        "body": body,
                    }
                ],
            }
        )
    return result


def generated_calendar(count: int, people: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for index in range(count):
        project = PROJECTS[index % len(PROJECTS)]
        start = datetime(2026, 8, 1, 15, tzinfo=timezone.utc) + timedelta(days=index)
        result.append(
            {
                "id": f"cal_{project.lower()}_{index:03d}",
                "title": f"{project} launch readiness review",
                "starts_at": start.isoformat().replace("+00:00", "Z"),
                "attendees": [
                    people[index % len(people)]["email"],
                    people[(index + 7) % len(people)]["email"],
                ],
            }
        )
    return result


def generated_knowledge(count: int) -> list[dict[str, str]]:
    result = []
    for index in range(count):
        project = PROJECTS[index % len(PROJECTS)]
        result.append(
            {
                "id": f"kb_{project.lower()}_{index:03d}",
                "title": f"{project} launch checklist revision {index % 5}",
                "body": (
                    f"General guidance for {project}. Verify current evidence and approvals in "
                    "the owning operational system; this document is not a status record."
                ),
                "updated_at": timestamp(index, hour=9),
            }
        )
    return result


def generated_files(count: int, people: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "id": f"file_{PROJECTS[index % len(PROJECTS)].lower()}_{index:03d}",
            "name": f"{PROJECTS[index % len(PROJECTS)].lower()}-security-evidence-notes-{index:03d}.pdf",
            "owner": people[(index + 3) % len(people)]["email"],
            "body": (
                "Archived or draft evidence notes for another release. Confirm the current status "
                "in that release's evidence register."
            ),
            "updated_at": timestamp(index, hour=11),
        }
        for index in range(count)
    ]


def generated_structured_files(
    count: int, people: list[dict[str, str]]
) -> list[dict[str, Any]]:
    result = []
    for index in range(count):
        project = PROJECTS[index % len(PROJECTS)]
        owner = people[(index + 5) % len(people)]["email"]
        result.append(
            {
                "id": f"json_{project.lower()}_{index:03d}",
                "name": f"{project.lower()}-launch-evidence-register-{index:03d}.json",
                "owner": owner,
                "content_type": "application/json",
                "updated_at": timestamp(index, hour=12),
                "content": {
                    "release": {"name": f"{project} release {index:03d}", "status": "archived"},
                    "evidence": {
                        "security": {"status": "approved", "owner": owner},
                        "product": {"status": "approved", "owner": owner},
                    },
                    "history": [
                        {"at": timestamp(index), "event": "evidence register archived"}
                    ],
                },
            }
        )
    return result


def generated_tasks(count: int, people: list[dict[str, str]]) -> list[dict[str, str]]:
    statuses = ["backlog", "in_progress", "blocked", "done"]
    return [
        {
            "id": f"task_{PROJECTS[index % len(PROJECTS)].lower()}_{index:03d}",
            "title": f"{PROJECTS[index % len(PROJECTS)]} compliance evidence item {index:03d}",
            "status": statuses[index % len(statuses)],
            "owner": people[(index + 13) % len(people)]["email"],
            "due_at": timestamp(index, hour=17),
        }
        for index in range(count)
    ]


def generated_metrics(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"metric_{PROJECTS[index % len(PROJECTS)].lower()}_{index:03d}",
            "name": f"{PROJECTS[index % len(PROJECTS)].lower()}_adoption",
            "value": 20 + (index * 7) % 79,
            "period": f"2026-{(index % 8) + 1:02d}",
        }
        for index in range(count)
    ]


def generated_tickets(count: int) -> list[dict[str, str]]:
    statuses = ["resolved", "closed", "monitoring"]
    return [
        {
            "id": f"ticket_{PROJECTS[index % len(PROJECTS)].lower()}_{index:03d}",
            "title": f"{PROJECTS[index % len(PROJECTS)]} network incident follow-up {index:03d}",
            "status": statuses[index % len(statuses)],
            "body": (
                f"Historical incident {index:03d} affected a test environment and has no bearing "
                "on the current Q3 launch."
            ),
        }
        for index in range(count)
    ]


def build(base: dict[str, Any]) -> dict[str, Any]:
    world = copy.deepcopy(base)
    world["world_version"] = "v2"
    world["fixture_metadata"] = {
        "generator": "scripts/generate_world_v2.py",
        "design": "deterministic scale, ambiguity, pagination, stale records, and large JSON",
    }

    people = place_anchors(generated_people(72), base["people"], [2, 18, 37])
    world["people"] = people
    world["mail_threads"] = place_anchors(
        generated_mail(78, people), base["mail_threads"], [6, 31]
    )
    world["chat_threads"] = place_anchors(
        generated_chat(78, people), base["chat_threads"], [6, 35]
    )
    world["calendar_events"] = place_anchors(
        generated_calendar(49, people), base["calendar_events"], [6]
    )
    world["knowledge_documents"] = place_anchors(
        generated_knowledge(44), base["knowledge_documents"], [6]
    )
    world["files"] = place_anchors(generated_files(39, people), base["files"], [6])

    launch_register = copy.deepcopy(base["structured_files"][0])
    launch_register["content"]["appendix"] = [
        {
            "control_id": f"CTRL-{index:04d}",
            "status": "not_applicable" if index % 5 else "complete",
            "note": "Background control retained in the historical appendix.",
        }
        for index in range(300)
    ]
    world["structured_files"] = place_anchors(
        generated_structured_files(24, people), [launch_register], [6]
    )
    world["project_tasks"] = place_anchors(
        generated_tasks(59, people), base["project_tasks"], [6]
    )
    world["analytics_metrics"] = place_anchors(
        generated_metrics(39), base["analytics_metrics"], [6]
    )
    world["support_tickets"] = place_anchors(
        generated_tickets(49), base["support_tickets"], [6]
    )
    return world


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if output differs; do not write.")
    args = parser.parse_args()
    payload = json.dumps(build(json.loads(args.base.read_text())), indent=2) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text() != payload:
            raise SystemExit(f"{args.output} is missing or not reproducible")
        print(f"world-v2 reproducibility check passed: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    print(f"Wrote deterministic world-v2 fixture: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
