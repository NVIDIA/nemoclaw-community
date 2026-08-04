#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve configured GitLab project paths to canonical numeric IDs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.casefold() == "https" else 80
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), port


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent a GitLab token from following redirects to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if origin(req.full_url) != origin(target):
            raise urllib.error.URLError("cross-origin GitLab redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, target)


def open_same_origin(request: urllib.request.Request, timeout: int = 30):
    opener = urllib.request.build_opener(SameOriginRedirectHandler())
    return opener.open(request, timeout=timeout)


def resolve_project(api_url: str, token: str, project: str) -> tuple[str, int]:
    # Numeric IDs keep the runtime policy canonical and avoid differences in
    # how GitLab front doors normalize encoded namespace separators.
    query = urllib.parse.urlencode(
        {
            "search": project,
            "search_namespaces": "true",
            "simple": "true",
            "per_page": "100",
        }
    )
    url = f"{api_url.rstrip('/')}/projects?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nemoclaw-gitlab-project-resolver/1.0",
        },
        method="GET",
    )
    try:
        with open_same_origin(request, timeout=30) as response:
            results = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"failed to resolve GitLab project {project!r}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not isinstance(results, list):
        raise SystemExit(f"GitLab returned an invalid project search for {project!r}")
    exact_matches = [
        item
        for item in results
        if isinstance(item, dict)
        and isinstance(item.get("path_with_namespace"), str)
        and item["path_with_namespace"].casefold() == project.casefold()
    ]
    if len(exact_matches) != 1:
        raise SystemExit(
            f"GitLab did not return exactly one exact project match for {project!r}"
        )

    project_id = exact_matches[0].get("id")
    canonical = exact_matches[0].get("path_with_namespace")
    if not isinstance(project_id, int) or project_id < 1:
        raise SystemExit(f"GitLab returned an invalid ID for {project!r}")
    if not isinstance(canonical, str) or canonical.casefold() != project.casefold():
        raise SystemExit(f"GitLab returned a mismatched project for {project!r}")
    return project, project_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("projects", nargs="+")
    args = parser.parse_args()

    token = os.environ.get("GITLAB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITLAB_TOKEN is required to resolve project IDs")

    for project in args.projects:
        canonical, project_id = resolve_project(args.api_url, token, project)
        print(f"{canonical}={project_id}")


if __name__ == "__main__":
    main()
