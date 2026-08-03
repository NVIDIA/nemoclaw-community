#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check a pull request title against the canonical title convention."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = (
    ROOT
    / ".agents/skills/nemoclaw-community-maintainer-policies/references/label-taxonomy.json"
)


def is_valid_title(title: str) -> bool:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return re.fullmatch(taxonomy["title_convention"]["pattern"], title) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="emit a GitHub warning instead of failing",
    )
    args = parser.parse_args()

    if is_valid_title(args.title):
        print("Pull request title follows the canonical convention")
        return 0

    message = (
        "Pull request title must use feat, fix, docs, chore, refactor, test, ci, "
        "or perf, with an optional lowercase scope"
    )
    if args.advisory:
        print(f"::warning title=PR title taxonomy::{message}")
        return 0
    print(message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
