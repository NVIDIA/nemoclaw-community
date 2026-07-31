#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Authenticated, project-scoped GitLab REST GET helper."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API = "https://gitlab.example.com/api/v4"
PROJECT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+$"
)
PARAM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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


def load_env_defaults() -> None:
    hermes_home = Path(os.environ.get("HERMES_HOME", "/sandbox/.hermes-data"))
    candidates = (
        hermes_home / ".env",
        Path("/sandbox/.hermes-data/.env"),
        Path("/sandbox/.hermes/.env"),
    )
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if not os.environ.get(key):
                os.environ[key] = value.strip()


def allowed_projects() -> list[str]:
    load_env_defaults()
    raw = os.environ.get("GITLAB_READONLY_PROJECTS", "")
    projects = [item.strip() for item in raw.split(",") if item.strip()]
    if not projects:
        raise SystemExit("GITLAB_READONLY_PROJECTS is empty")
    invalid = [item for item in projects if not PROJECT_RE.fullmatch(item)]
    if invalid:
        raise SystemExit(f"invalid GitLab project path: {invalid[0]!r}")
    return projects


def choose_project(value: str | None) -> str:
    projects = allowed_projects()
    if value:
        matches = [item for item in projects if item.casefold() == value.casefold()]
        if not matches:
            raise SystemExit(f"project {value!r} is outside GITLAB_READONLY_PROJECTS")
        return matches[0]
    if len(projects) != 1:
        raise SystemExit(
            "multiple GitLab projects are configured; pass --project group/project"
        )
    return projects[0]


def project_id(project: str) -> int:
    load_env_defaults()
    raw = os.environ.get("GITLAB_READONLY_PROJECT_IDS", "")
    mapping: dict[str, int] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        path, separator, value = item.strip().rpartition("=")
        if not separator or not path or not value.isdigit() or int(value) < 1:
            raise SystemExit("GITLAB_READONLY_PROJECT_IDS contains an invalid mapping")
        mapping[path.casefold()] = int(value)
    resolved = mapping.get(project.casefold())
    if resolved is None:
        raise SystemExit(f"no numeric GitLab project ID is configured for {project!r}")
    return resolved


def clean_route(value: str) -> str:
    route = value.strip()
    if route in {"", ".", "/"}:
        return ""
    if "://" in route or "?" in route or "#" in route or "\\" in route:
        raise SystemExit("route must be a project-relative REST path")
    parts = route.strip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SystemExit("route contains an invalid path segment")
    normalized = "/".join(
        urllib.parse.quote(urllib.parse.unquote(part), safe="") for part in parts
    )
    if not any(
        normalized == safe or normalized.startswith(f"{safe}/")
        for safe in SAFE_ROUTES
    ):
        raise SystemExit(f"route {route!r} is outside the GitLab read policy")
    return normalized


def parse_param(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("query params must use KEY=VALUE")
    key, item = value.split("=", 1)
    if not PARAM_RE.fullmatch(key):
        raise argparse.ArgumentTypeError(f"invalid query parameter name: {key!r}")
    if any(char in item for char in "\r\n\0"):
        raise argparse.ArgumentTypeError(
            "query parameter contains a control character"
        )
    return key, item


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def auth_header() -> str:
    load_env_defaults()
    token = os.environ.get("GITLAB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GitLab provider credential is unavailable")
    return f"Bearer {token}"


def api_url() -> str:
    load_env_defaults()
    value = os.environ.get("GITLAB_API_URL", DEFAULT_API).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path != "/api/v4"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise SystemExit(
            "invalid GITLAB_API_URL; expected https://host[:port]/api/v4"
        )
    return value


def get_json(
    path: str, params: dict[str, str] | None = None
) -> tuple[Any, dict[str, str]]:
    url = f"{api_url()}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": auth_header(),
            "User-Agent": "nemoclaw-gitlab-readonly/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return json.load(response), headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"GitLab request failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        if body:
            print(body[:2000], file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"GitLab request failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def project_fields(value: Any, fields: list[str]) -> Any:
    if not fields:
        return value

    def one(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        return {field: item.get(field) for field in fields}

    return [one(item) for item in value] if isinstance(value, list) else one(value)


def run_get(args: argparse.Namespace) -> Any:
    project = choose_project(args.project)
    route = clean_route(args.route)
    path = f"/projects/{project_id(project)}" + (f"/{route}" if route else "")
    params = dict(args.param)
    fields = (
        [item.strip() for item in args.fields.split(",") if item.strip()]
        if args.fields
        else []
    )

    if not (args.paginate or args.count or args.limit):
        data, _headers = get_json(path, params)
        return {"project": project, "data": project_fields(data, fields)}

    results: list[Any] = []
    page = 1
    complete = True
    while True:
        page_params = dict(params)
        page_params.update({"page": str(page), "per_page": "100"})
        data, headers = get_json(path, page_params)
        if not isinstance(data, list):
            raise SystemExit("pagination requested for a non-list GitLab response")
        results.extend(data)
        next_page = headers.get("x-next-page", "")
        if args.limit and len(results) >= args.limit:
            complete = len(results) <= args.limit and not bool(next_page)
            results = results[: args.limit]
            break
        if not next_page:
            break
        page = int(next_page)

    if args.count:
        return {"project": project, "complete": complete, "count": len(results)}
    return {
        "project": project,
        "complete": complete,
        "data": project_fields(results, fields),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("identity", help="Show the authenticated GitLab identity")
    get_parser = subparsers.add_parser(
        "get", help="GET a project-relative GitLab route"
    )
    get_parser.add_argument("route")
    get_parser.add_argument("--project")
    get_parser.add_argument("--param", action="append", type=parse_param, default=[])
    get_parser.add_argument("--paginate", action="store_true")
    get_parser.add_argument("--count", action="store_true")
    get_parser.add_argument("--limit", type=positive_int)
    get_parser.add_argument("--fields")
    args = parser.parse_args()

    if args.command == "identity":
        data, _headers = get_json("/user")
        output = {key: data.get(key) for key in ("id", "username", "name")}
    else:
        output = run_get(args)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
