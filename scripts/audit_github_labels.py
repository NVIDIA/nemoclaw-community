#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compare live GitHub labels with the canonical taxonomy without writing."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = (
    ROOT
    / ".agents/skills/nemoclaw-community-maintainer-policies/references/label-taxonomy.json"
)


def target_labels(taxonomy: dict[str, Any]) -> dict[str, dict[str, str]]:
    entries = list(taxonomy["canonical_labels"])
    for family in taxonomy["label_families"].values():
        entries.extend(family["entries"])
    return {entry["name"]: entry for entry in entries}


def read_live_labels(repo: str) -> dict[str, dict[str, str]]:
    command = [
        "gh",
        "label",
        "list",
        "--repo",
        repo,
        "--limit",
        "500",
        "--json",
        "name,description,color",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return {entry["name"]: entry for entry in json.loads(result.stdout)}


def read_live_labels_file(path: Path) -> dict[str, dict[str, str]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in entries}


def build_audit(
    taxonomy: dict[str, Any], live: dict[str, dict[str, str]]
) -> dict[str, list[Any]]:
    target = target_labels(taxonomy)
    create = [target[name] for name in sorted(set(target) - set(live))]
    update: list[dict[str, Any]] = []
    for name in sorted(set(target) & set(live)):
        expected = target[name]
        actual = live[name]
        differences = {}
        for field in ("description", "color"):
            if (actual.get(field) or "").lower() != expected[field].lower():
                differences[field] = {
                    "current": actual.get(field) or "",
                    "expected": expected[field],
                }
        if differences:
            update.append({"name": name, "differences": differences})

    legacy = [name for name in taxonomy["legacy_labels"] if name in live]
    unknown = sorted(set(live) - set(target) - set(legacy))
    return {"create": create, "update": update, "legacy": legacy, "unknown": unknown}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument(
        "--live-json",
        type=Path,
        help="read gh label-list JSON from a file instead of contacting GitHub",
    )
    args = parser.parse_args()

    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    repo = args.repo or taxonomy["repo"]
    try:
        live = (
            read_live_labels_file(args.live_json)
            if args.live_json
            else read_live_labels(repo)
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc))
        print("Unable to read live labels. No GitHub labels were changed.")
        return 2

    audit = build_audit(taxonomy, live)
    print(json.dumps({"repo": repo, **audit}, indent=2, sort_keys=True))
    print("Dry run only: no GitHub labels were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
