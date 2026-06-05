#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Authenticated, repo-scoped GitHub REST GET helper."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]+$")
PARAM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GENERIC_ROOTS = {
    "issues",
    "labels",
    "milestones",
    "pulls",
    "commits",
    "branches",
    "contents",
    "readme",
}


def repo_name() -> str:
    repo = (os.environ.get("GITHUB_READONLY_REPO") or "NVIDIA/OpenShell").strip()
    if not REPO_RE.fullmatch(repo):
        raise SystemExit(f"invalid GITHUB_READONLY_REPO {repo!r}; expected owner/repo")
    return repo


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def per_page(value: str) -> int:
    parsed = positive_int(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError("GitHub per_page maximum is 100")
    return parsed


def optional_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or positive")
    return parsed


def load_env_defaults() -> None:
    hermes_home = Path(os.environ.get("HERMES_HOME", "/sandbox/.hermes-data"))
    for env_file in (hermes_home / ".env", Path("/sandbox/.hermes-data/.env"), Path("/sandbox/.hermes/.env")):
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if not os.environ.get(key):
                os.environ[key] = value.strip()


def auth_header() -> str | None:
    load_env_defaults()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return None
    return f"Bearer {token}"


def clean_contents_path(value: str) -> str:
    value = value.strip("/")
    if not value:
        return ""
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise argparse.ArgumentTypeError("path must be a repository-relative path")
    return "/".join(urllib.parse.quote(part, safe="") for part in parts)


def clean_repo_route(value: str) -> str:
    route = value.strip()
    if route in {"", ".", "/"}:
        return ""
    if "://" in route or "?" in route or "#" in route or "\\" in route:
        raise argparse.ArgumentTypeError("route must be a repo-relative REST path, not a URL or query string")
    route = route.strip("/")
    parts = route.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise argparse.ArgumentTypeError("route must not contain empty, current, or parent-directory segments")
    if parts[0] == "repos":
        raise argparse.ArgumentTypeError("route must be relative to the configured repo, for example 'issues/123'")
    if parts[0] not in GENERIC_ROOTS:
        allowed = ", ".join(sorted(GENERIC_ROOTS))
        raise argparse.ArgumentTypeError(f"route root {parts[0]!r} is outside policy; allowed roots: {allowed}")
    return "/".join(urllib.parse.quote(urllib.parse.unquote(part), safe="") for part in parts)


def parse_param(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("query params must use KEY=VALUE")
    key, param_value = value.split("=", 1)
    key = key.strip()
    if not PARAM_RE.fullmatch(key):
        raise argparse.ArgumentTypeError(f"invalid query parameter name: {key!r}")
    if any(ch in param_value for ch in "\r\n\0"):
        raise argparse.ArgumentTypeError("query parameter values must not contain control characters")
    return key, param_value


def params_dict(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return {key: value for key, value in pairs}


def get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{API}{path}"
    if params:
        clean_params = {k: v for k, v in params.items() if v is not None}
        if clean_params:
            url = f"{url}?{urllib.parse.urlencode(clean_params)}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nemoclaw-github-readonly/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    auth = auth_header()
    if auth:
        headers["Authorization"] = auth

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub request failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        reset = exc.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                reset_dt = dt.datetime.fromtimestamp(int(reset), tz=dt.UTC)
                print(f"GitHub rate limit resets at {reset_dt.isoformat()}", file=sys.stderr)
            except ValueError:
                pass
        if body:
            print(body[:2000], file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"GitHub request failed: {exc}", file=sys.stderr)
        print(
            "Retry this same github_readonly.py command once. Do not inspect "
            "token, .env, or proxy variables; the helper loads provider "
            "placeholders itself.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def repo_path(suffix: str = "") -> str:
    repo = repo_name()
    return f"/repos/{repo}{suffix}"


def paged_items(path: str, params: dict[str, Any] | None = None) -> list[Any]:
    items, _complete = collect_items(path, params=params, paginate=True)
    return items


def collect_items(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    paginate: bool,
    limit: int | None = None,
    exclude_pulls: bool = False,
    page_size: int = 100,
    max_pages: int = 0,
) -> tuple[list[Any], bool]:
    results: list[Any] = []
    page = int((params or {}).get("page", 1) or 1)
    base_params = {k: v for k, v in (params or {}).items() if k not in {"page", "per_page"}}

    while True:
        page_params = dict(base_params)
        page_params.update({"per_page": min(page_size, 100), "page": page})
        page_items = get_json(path, page_params)
        if not isinstance(page_items, list):
            raise SystemExit(f"unexpected GitHub list response for {path}")
        raw_count = len(page_items)
        if exclude_pulls:
            page_items = issue_only(page_items)
        results.extend(page_items)
        if limit is not None and len(results) >= limit:
            return results[:limit], True
        if raw_count < min(page_size, 100):
            return results, True
        if not paginate:
            return results, False
        page += 1
        if max_pages and page > max_pages:
            return results, False


def issue_only(items: list[Any]) -> list[Any]:
    return [item for item in items if isinstance(item, dict) and "pull_request" not in item]


def issue_counts() -> dict[str, int]:
    counts = {"open": 0, "closed": 0, "total": 0}
    for item in issue_only(paged_items(repo_path("/issues"), {"state": "all"})):
        state = item.get("state")
        if state in ("open", "closed"):
            counts[state] += 1
            counts["total"] += 1
    return counts


def pull_counts(state: str) -> dict[str, int]:
    if state == "all":
        open_count = len(paged_items(repo_path("/pulls"), {"state": "open"}))
        closed_count = len(paged_items(repo_path("/pulls"), {"state": "closed"}))
        return {"open": open_count, "closed": closed_count, "total": open_count + closed_count}
    count = len(paged_items(repo_path("/pulls"), {"state": state}))
    return {state: count, "total": count}


def project_field(value: Any, field: str) -> Any:
    current = value
    for part in field.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def project_fields(data: Any, fields: list[str]) -> Any:
    if not fields:
        return data

    def project_one(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        return {field: project_field(item, field) for field in fields}

    if isinstance(data, list):
        return [project_one(item) for item in data]
    return project_one(data)


def generic_get(args: argparse.Namespace) -> Any:
    try:
        route = clean_repo_route(args.route)
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(str(exc)) from exc
    params = params_dict(args.param)
    fields = [field.strip() for field in args.fields.split(",") if field.strip()] if args.fields else []
    path = repo_path(f"/{route}" if route else "")

    list_mode = args.paginate or args.count or args.limit is not None or args.exclude_pulls
    if list_mode:
        items, complete = collect_items(
            path,
            params=params,
            paginate=args.paginate or args.count,
            limit=args.limit,
            exclude_pulls=args.exclude_pulls,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
        if args.count:
            return {"count": len(items), "complete": complete}
        return project_fields(items, fields)

    return project_fields(get_json(path, params), fields)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generic = sub.add_parser("get")
    generic.add_argument("route", help="repo-relative REST route, e.g. '.', 'issues', 'issues/123/comments', 'pulls/123/files'")
    generic.add_argument("--param", action="append", type=parse_param, default=[], metavar="KEY=VALUE")
    generic.add_argument("--paginate", action="store_true", help="fetch every page for list responses")
    generic.add_argument("--count", action="store_true", help="print a count for list responses; implies pagination")
    generic.add_argument("--limit", type=positive_int, default=None, help="maximum list items to return after filtering")
    generic.add_argument("--page-size", type=per_page, default=100)
    generic.add_argument("--max-pages", type=optional_positive_int, default=0, help="pagination safety cap; 0 means no cap")
    generic.add_argument("--exclude-pulls", action="store_true", help="filter pull requests out of GitHub's issues endpoint")
    generic.add_argument("--fields", default="", help="comma-separated top-level or dotted fields to keep")

    sub.add_parser("rate-limit")
    sub.add_parser("repo")
    sub.add_parser("readme")

    labels = sub.add_parser("labels")
    labels.add_argument("--limit", type=per_page, default=30)

    milestones = sub.add_parser("milestones")
    milestones.add_argument("--state", choices=["open", "closed", "all"], default="open")
    milestones.add_argument("--limit", type=per_page, default=30)

    issues = sub.add_parser("issues")
    issues.add_argument("--state", choices=["open", "closed", "all"], default="open")
    issues.add_argument("--limit", type=per_page, default=30)

    sub.add_parser("issue-counts")

    issue = sub.add_parser("issue")
    issue.add_argument("number", type=positive_int)

    issue_comments = sub.add_parser("issue-comments")
    issue_comments.add_argument("number", type=positive_int)
    issue_comments.add_argument("--limit", type=per_page, default=30)

    pulls = sub.add_parser("pulls")
    pulls.add_argument("--state", choices=["open", "closed", "all"], default="open")
    pulls.add_argument("--limit", type=per_page, default=30)

    pull_counts_parser = sub.add_parser("pull-counts")
    pull_counts_parser.add_argument("--state", choices=["open", "closed", "all"], default="open")

    pull = sub.add_parser("pull")
    pull.add_argument("number", type=positive_int)

    for name in ("pull-files", "pull-commits", "pull-reviews", "pull-comments"):
        p = sub.add_parser(name)
        p.add_argument("number", type=positive_int)
        p.add_argument("--limit", type=per_page, default=30)

    commits = sub.add_parser("commits")
    commits.add_argument("--limit", type=per_page, default=30)

    branches = sub.add_parser("branches")
    branches.add_argument("--limit", type=per_page, default=30)

    contents = sub.add_parser("contents")
    contents.add_argument("path", nargs="?", type=clean_contents_path, default="")

    args = parser.parse_args()

    if args.command == "get":
        data = generic_get(args)
    elif args.command == "rate-limit":
        data = get_json("/rate_limit")
    elif args.command == "repo":
        data = get_json(repo_path())
    elif args.command == "readme":
        data = get_json(repo_path("/readme"))
    elif args.command == "labels":
        data = get_json(repo_path("/labels"), {"per_page": args.limit})
    elif args.command == "milestones":
        data = get_json(repo_path("/milestones"), {"state": args.state, "per_page": args.limit})
    elif args.command == "issues":
        collected: list[Any] = []
        page = 1
        while len(collected) < args.limit:
            items = get_json(repo_path("/issues"), {"state": args.state, "per_page": 100, "page": page})
            if not isinstance(items, list):
                raise SystemExit("unexpected GitHub issues response")
            collected.extend(issue_only(items))
            if len(items) < 100:
                break
            page += 1
        data = collected[: args.limit]
    elif args.command == "issue-counts":
        data = issue_counts()
    elif args.command == "issue":
        data = get_json(repo_path(f"/issues/{args.number}"))
    elif args.command == "issue-comments":
        data = get_json(repo_path(f"/issues/{args.number}/comments"), {"per_page": args.limit})
    elif args.command == "pulls":
        data = get_json(repo_path("/pulls"), {"state": args.state, "per_page": args.limit})
    elif args.command == "pull-counts":
        data = pull_counts(args.state)
    elif args.command == "pull":
        data = get_json(repo_path(f"/pulls/{args.number}"))
    elif args.command == "pull-files":
        data = get_json(repo_path(f"/pulls/{args.number}/files"), {"per_page": args.limit})
    elif args.command == "pull-commits":
        data = get_json(repo_path(f"/pulls/{args.number}/commits"), {"per_page": args.limit})
    elif args.command == "pull-reviews":
        data = get_json(repo_path(f"/pulls/{args.number}/reviews"), {"per_page": args.limit})
    elif args.command == "pull-comments":
        data = get_json(repo_path(f"/pulls/{args.number}/comments"), {"per_page": args.limit})
    elif args.command == "commits":
        data = get_json(repo_path("/commits"), {"per_page": args.limit})
    elif args.command == "branches":
        data = get_json(repo_path("/branches"), {"per_page": args.limit})
    elif args.command == "contents":
        suffix = "/contents" if not args.path else f"/contents/{args.path}"
        data = get_json(repo_path(suffix))
    else:
        parser.error(f"unknown command: {args.command}")

    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
