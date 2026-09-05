#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve GitHub repository scope and stage its exact read-only policy rules."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from .configuration import ConfigurationError, github_readonly_repositories
except ImportError:
    from configuration import ConfigurationError, github_readonly_repositories


POLICY_MARKER = "      # __GITHUB_READONLY_REPOSITORY_RULES__"
REPOSITORY_PATH_SUFFIXES = (
    "",
    "/issues",
    "/issues/**",
    "/labels",
    "/labels/**",
    "/milestones",
    "/milestones/**",
    "/pulls",
    "/pulls/**",
    "/commits",
    "/commits/**",
    "/branches",
    "/branches/**",
    "/contents",
    "/contents/**",
    "/readme",
)


def render_policy(template: str, repositories: Sequence[str]) -> str:
    validated = github_readonly_repositories(
        {"GITHUB_READONLY_REPOS": ",".join(repositories)}
    )
    if template.count(POLICY_MARKER) != 1:
        raise ConfigurationError(
            "policy template must contain one GitHub repository rule marker"
        )

    rules = [
        "      - allow: { method: GET, path: /repos/"
        f"{repository}{suffix} }}"
        for repository in validated
        for suffix in REPOSITORY_PATH_SUFFIXES
    ]
    return template.replace(POLICY_MARKER, "\n".join(rules))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("resolve", help="Print the canonical comma-separated list")
    stage = subparsers.add_parser(
        "stage-policy", help="Write a policy with exact repository rules"
    )
    stage.add_argument("--template", required=True, type=Path)
    stage.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repositories = github_readonly_repositories(os.environ)
        if args.command == "resolve":
            print(",".join(repositories))
        elif args.command == "stage-policy":
            template = args.template.read_text(encoding="utf-8")
            args.output.write_text(
                render_policy(template, repositories), encoding="utf-8"
            )
        return 0
    except (ConfigurationError, OSError) as error:
        print(f"GitHub repository configuration failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
