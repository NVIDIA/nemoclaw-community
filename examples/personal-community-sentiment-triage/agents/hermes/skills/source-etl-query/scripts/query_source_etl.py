#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = value.strip()
    return loaded


def env_optional(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for env_path in (Path("/sandbox/.hermes/.env"), Path("/sandbox/.hermes-data/.env")):
        file_value = load_env_file(env_path).get(name, "").strip()
        if file_value:
            return file_value
    return ""


def api_base_url() -> str:
    configured = env_optional("SOURCE_ETL_API_URL")
    if configured:
        return configured.rstrip("/")
    host = env_optional("SOURCE_ETL_API_HOST") or "host.openshell.internal"
    port = env_optional("SOURCE_ETL_API_PORT") or "3100"
    return f"http://{host}:{port}"


def build_request(kind: str, search: str | None, limit: int) -> tuple[str, list[str]]:
    if kind == "github-issues":
        path = "/github_issues"
        columns = ["number", "state", "updated_at", "title"]
        order = "updated_at.desc"
        search_columns = ["title", "body"]
    elif kind == "github-prs":
        path = "/github_prs"
        columns = ["number", "state", "updated_at", "title"]
        order = "updated_at.desc"
        search_columns = ["title", "body"]
    elif kind == "github-discussions":
        path = "/github_discussions"
        columns = ["number", "updated_at", "title"]
        order = "updated_at.desc"
        search_columns = ["title", "body"]
    elif kind == "forum-topics":
        path = "/forum_topics"
        columns = ["topic_id", "last_posted_at", "title"]
        order = "last_posted_at.desc"
        search_columns = ["title", "slug", "raw_payload_text"]
    else:
        raise ValueError(f"unsupported kind: {kind}")

    query: list[tuple[str, str]] = [
        ("select", ",".join(columns)),
        ("order", order),
        ("limit", str(limit)),
    ]
    if search:
        escaped = search.replace("%", "").replace(",", " ").replace("(", " ").replace(")", " ").strip()
        filters = ",".join(f"{column}.ilike.*{escaped}*" for column in search_columns)
        query.append(("or", f"({filters})"))
    return f"{path}?{urllib.parse.urlencode(query)}", columns


def fetch_rows(url: str) -> list[dict[str, object]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "nemoclaw-source-etl-query/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def print_rows(rows: list[dict[str, object]], columns: list[str]) -> None:
    print("\t".join(columns))
    for row in rows:
        values: list[str] = []
        for column in columns:
            value = row.get(column, "")
            values.append("" if value is None else str(value).replace("\t", " ").replace("\n", " "))
        print("\t".join(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "kind",
        choices=["github-issues", "github-prs", "github-discussions", "forum-topics"],
    )
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    relative_url, columns = build_request(args.kind, args.search, args.limit)
    url = f"{api_base_url()}{relative_url}"
    try:
        rows = fetch_rows(url)
    except Exception as exc:
        print(f"source-etl query failed: {exc}", file=sys.stderr)
        return 1
    print_rows(rows, columns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
