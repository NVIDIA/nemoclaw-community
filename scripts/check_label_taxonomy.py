#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate the canonical NemoClaw Community label taxonomy."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / ".agents/skills/nemoclaw-community-maintainer-policies/references"
TAXONOMY_PATH = POLICY_DIR / "label-taxonomy.json"
TAXONOMY_MARKDOWN_PATH = POLICY_DIR / "label-taxonomy.md"


def load_taxonomy() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def iter_label_entries(taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    entries = list(taxonomy["canonical_labels"])
    for family in taxonomy["label_families"].values():
        entries.extend(family["entries"])
    return entries


def validate_taxonomy() -> list[str]:
    errors: list[str] = []
    taxonomy = load_taxonomy()
    markdown = TAXONOMY_MARKDOWN_PATH.read_text(encoding="utf-8")
    entries = iter_label_entries(taxonomy)

    if taxonomy.get("repo") != "NVIDIA/nemoclaw-community":
        errors.append("taxonomy repo must be NVIDIA/nemoclaw-community")

    baseline_commit = taxonomy.get("derived_from", {}).get("baseline_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", baseline_commit):
        errors.append("derived_from.baseline_commit must be a full Git commit SHA")

    names = [entry["name"] for entry in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate labels: {', '.join(duplicates)}")

    for entry in entries:
        name = entry.get("name", "")
        if not entry.get("description"):
            errors.append(f"{name}: missing description")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", entry.get("color", "")):
            errors.append(f"{name}: color must be six hexadecimal characters")
        if f"`{name}`" not in markdown:
            errors.append(f"{name}: missing from label-taxonomy.md")

    for family_name, family in taxonomy["label_families"].items():
        prefix = family["prefix"]
        for entry in family["entries"]:
            if not entry["name"].startswith(prefix):
                errors.append(f"{entry['name']}: does not match {family_name} prefix {prefix!r}")

    known = set(names)
    for group_name, members in taxonomy["mutually_exclusive_groups"].items():
        unknown = sorted(set(members) - known)
        if unknown:
            errors.append(f"{group_name}: unknown members {', '.join(unknown)}")

    if "security" in known:
        errors.append("supplemental public security label must not be canonical")
    if "area: security" not in known:
        errors.append("area: security must be canonical")

    try:
        re.compile(taxonomy["title_convention"]["pattern"])
    except re.error as exc:
        errors.append(f"invalid title pattern: {exc}")

    forms = {
        "bug.yml": "Bug",
        "feature.yml": "Enhancement",
        "documentation.yml": "Documentation",
    }
    for filename, issue_type in forms.items():
        path = ROOT / ".github/ISSUE_TEMPLATE" / filename
        if not path.exists():
            errors.append(f"missing issue form: {filename}")
            continue
        text = path.read_text(encoding="utf-8")
        if f"type: {issue_type}" not in text:
            errors.append(f"{filename}: missing native Issue Type {issue_type}")
        for legacy in ("bug", "enhancement", "documentation"):
            if re.search(rf'^labels:.*["\[]?{re.escape(legacy)}["\]]?', text, re.MULTILINE):
                errors.append(f"{filename}: applies legacy type label {legacy}")

    labels_entrypoint = (ROOT / ".github/LABELS.md").read_text(encoding="utf-8")
    if "nemoclaw-community-maintainer-policies" not in labels_entrypoint:
        errors.append(".github/LABELS.md must point to the canonical policy package")

    contributor_skill = (
        ROOT / ".agents/skills/nemoclaw-community-contributor-examples/SKILL.md"
    ).read_text(encoding="utf-8")
    if "nemoclaw-community-maintainer-policies" not in contributor_skill:
        errors.append("contributor-example skill must route metadata to maintainer policy")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without modifying files")
    parser.parse_args()

    errors = validate_taxonomy()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Label taxonomy valid: {len(iter_label_entries(load_taxonomy()))} labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
