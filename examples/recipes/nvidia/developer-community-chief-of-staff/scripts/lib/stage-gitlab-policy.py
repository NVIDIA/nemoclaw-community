#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render project-scoped, GET-only GitLab rules into a staged policy."""

from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "__GITLAB_READONLY_RULES__"
SAFE_ROUTES = (
    "issues",
    "merge_requests",
    "repository/tree",
    "repository/branches",
    "repository/tags",
    "repository/commits",
    "repository/files",
    "repository/compare",
    "repository/contributors",
    "repository/languages",
    "repository/blame",
    "labels",
    "milestones",
    "releases",
)


def project_rules(project_spec: str) -> list[str]:
    project, separator, project_id = project_spec.rpartition("=")
    if not separator or not project or not project_id.isdigit() or int(project_id) < 1:
        raise ValueError(f"invalid GitLab project spec: {project_spec!r}")
    base = f"/api/v4/projects/{project_id}"
    paths = []
    for route in SAFE_ROUTES:
        paths.extend((f"{base}/{route}", f"{base}/{route}/**"))
    return paths


def render_policy(policy: str, project_specs: list[str]) -> str:
    if policy.count(MARKER) != 1:
        raise ValueError(f"expected exactly one {MARKER} marker")

    paths: list[str] = []
    for project_spec in project_specs:
        paths.extend(project_rules(project_spec))
    if not project_specs:
        paths = ["/api/v4/__gitlab_disabled__"]

    indent = "      "
    rendered = "\n".join(
        f'{indent}- allow: {{ method: GET, path: "{path}" }}' for path in paths
    )
    return policy.replace(f"{indent}{MARKER}", rendered)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy", type=Path)
    parser.add_argument("projects", nargs="*")
    args = parser.parse_args()

    policy = args.policy.read_text(encoding="utf-8")
    try:
        rendered = render_policy(policy, args.projects)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.policy.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
