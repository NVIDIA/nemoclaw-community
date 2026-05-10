#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def api_key() -> str:
    value = os.environ.get("TAVILY_API_KEY", "").strip()
    if value:
        return value
    # OpenShell resolves placeholders in HTTP headers at egress time.
    return "openshell:resolve:env:TAVILY_API_KEY"


def compact_result(item: dict[str, Any], include_raw_content: bool) -> dict[str, Any]:
    result = {
        "title": item.get("title"),
        "url": item.get("url"),
        "content": item.get("content"),
        "score": item.get("score"),
    }
    if item.get("published_date"):
        result["published_date"] = item.get("published_date")
    if include_raw_content and item.get("raw_content"):
        result["raw_content"] = item.get("raw_content")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Tavily and return compact JSON")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=8)
    parser.add_argument("--search-depth", choices=["basic", "advanced"], default="advanced")
    parser.add_argument("--topic", choices=["general", "news"], default="general")
    parser.add_argument("--time-range", choices=["day", "week", "month", "year", "d", "w", "m", "y"])
    parser.add_argument("--include-domains", help="Comma-separated domain allowlist")
    parser.add_argument("--exclude-domains", help="Comma-separated domain blocklist")
    parser.add_argument("--include-answer", action="store_true")
    parser.add_argument("--include-raw-content", action="store_true")
    parser.add_argument("--include-images", action="store_true")
    parser.add_argument("--include-usage", action="store_true")
    args = parser.parse_args()

    payload: dict[str, Any] = {
        "query": args.query,
        "max_results": max(1, min(args.max_results, 20)),
        "search_depth": args.search_depth,
        "topic": args.topic,
        "include_answer": args.include_answer,
        "include_raw_content": args.include_raw_content,
        "include_images": args.include_images,
        "include_usage": args.include_usage,
    }
    if args.time_range:
        payload["time_range"] = args.time_range
    include_domains = split_csv(args.include_domains)
    exclude_domains = split_csv(args.exclude_domains)
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nemoclaw-tavily-web-search/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"ok": False, "status": exc.code, "error": body[:1000]}))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    results = [
        compact_result(item, args.include_raw_content)
        for item in data.get("results", [])
    ]
    output: dict[str, Any] = {
        "ok": True,
        "query": args.query,
        "count": len(results),
        "results": results,
    }
    if data.get("answer"):
        output["answer"] = data.get("answer")
    if args.include_images and data.get("images"):
        output["images"] = data.get("images")
    if args.include_usage and data.get("usage"):
        output["usage"] = data.get("usage")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
