#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
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
    return (env_optional("TAVILY_API_BASE_URL") or "https://api.tavily.com").rstrip("/")


def api_key() -> str:
    key = env_optional("TAVILY_API_KEY")
    if not key:
        raise SystemExit("Missing TAVILY_API_KEY")
    return key


def post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{api_base_url()}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "User-Agent": "nemoclaw-tavily/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "http_error",
                    "status": err.code,
                    "reason": err.reason,
                    "body": body,
                },
                indent=2,
            )
        )
        raise SystemExit(4)
    except Exception as err:
        print(json.dumps({"ok": False, "error": "exception", "detail": str(err)}, indent=2))
        raise SystemExit(5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--search-depth", choices=["basic", "advanced"], default="basic")
    search.add_argument("--topic", choices=["general", "news", "finance"], default="general")
    search.add_argument("--max-results", type=int, default=5)
    search.add_argument("--time-range", choices=["day", "week", "month", "year", "d", "w", "m", "y"])
    search.add_argument("--include-answer", choices=["basic", "advanced"])
    search.add_argument("--include-raw-content", choices=["markdown", "text"])
    search.add_argument("--include-images", action="store_true")
    search.add_argument("--include-favicon", action="store_true")
    search.add_argument("--include-domain", action="append", default=[])
    search.add_argument("--exclude-domain", action="append", default=[])

    extract = subparsers.add_parser("extract")
    extract.add_argument("--url", action="append", required=True)
    extract.add_argument("--query")
    extract.add_argument("--extract-depth", choices=["basic", "advanced"], default="basic")
    extract.add_argument("--format", choices=["markdown", "text"], default="markdown")
    extract.add_argument("--chunks-per-source", type=int)
    extract.add_argument("--include-images", action="store_true")
    extract.add_argument("--include-favicon", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "search":
        payload: dict[str, object] = {
            "query": args.query,
            "search_depth": args.search_depth,
            "topic": args.topic,
            "max_results": args.max_results,
        }
        if args.time_range:
            payload["time_range"] = args.time_range
        if args.include_answer:
            payload["include_answer"] = args.include_answer
        if args.include_raw_content:
            payload["include_raw_content"] = args.include_raw_content
        if args.include_images:
            payload["include_images"] = True
        if args.include_favicon:
            payload["include_favicon"] = True
        if args.include_domain:
            payload["include_domains"] = args.include_domain
        if args.exclude_domain:
            payload["exclude_domains"] = args.exclude_domain
        result = post_json("/search", payload)
    else:
        payload = {
            "urls": args.url,
            "extract_depth": args.extract_depth,
            "format": args.format,
        }
        if args.query:
            payload["query"] = args.query
        if args.chunks_per_source is not None:
            payload["chunks_per_source"] = args.chunks_per_source
        if args.include_images:
            payload["include_images"] = True
        if args.include_favicon:
            payload["include_favicon"] = True
        result = post_json("/extract", payload)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
