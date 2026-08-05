#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Deterministically filter watchtower candidate items against seen-state and excludes.

Reads candidate items as JSON lines on stdin. Required fields are `topic_id`,
`url`, and `title`; any additional fields such as `snippet` or `content` are
preserved. Drops any item whose URL is already recorded in the state file, any
item for an unknown topic, and any item whose host matches that topic's optional
`exclude_domains` list (subdomain suffix match).

This script makes no network calls and no significance judgment — it only
enforces mechanical deduplication and explicit negative filters. The prompt and
LLM decide relevance, credibility, and significance. See skills/watchtower/SKILL.md.

Usage:
    <candidates.jsonl python3 diff_state.py --watchlist <path> --state <path> >survivors.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

_TOPIC_START_RE = re.compile(r"^\s*-\s*id:\s*(.+)$")
_EXCLUDE_DOMAINS_FIELD_RE = re.compile(r"^\s+exclude_domains:\s*(.*)$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [_strip_quotes(item) for item in raw.split(",") if _strip_quotes(item)]


def load_topic_excludes(watchlist_path: Path) -> dict[str, list[str]]:
    """Extract {topic_id: [exclude_domains]} from a watchlist YAML file.

    Uses the same restricted line-based reading as validate_watchlist.py. Run
    validate_watchlist.py first — this assumes a schema-valid file.
    """
    excludes_by_topic: dict[str, list[str]] = {}
    current_id: str | None = None
    for line in watchlist_path.read_text(encoding="utf-8").splitlines():
        topic_start = _TOPIC_START_RE.match(line)
        if topic_start:
            current_id = _strip_quotes(topic_start.group(1))
            excludes_by_topic.setdefault(current_id, [])
            continue
        exclude_field = _EXCLUDE_DOMAINS_FIELD_RE.match(line)
        if exclude_field and current_id is not None:
            excludes_by_topic[current_id] = _parse_list(exclude_field.group(1))
    return excludes_by_topic


def load_seen_urls(state_path: Path) -> set[str]:
    if not state_path.is_file():
        return set()
    text = state_path.read_text(encoding="utf-8").strip()
    if not text:
        return set()
    state = json.loads(text)
    return {item["url"] for item in state.get("items", [])}


def host_in_domains(host: str, domains: list[str]) -> bool:
    host = host.lower()
    for domain in domains:
        domain = domain.lower()
        if host == domain or host.endswith("." + domain):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Filter candidate items on stdin (JSON lines: topic_id, url, title, ...) "
            "against seen-state and optional exclude_domains rules. Surviving items "
            "are written to stdout as JSON lines, one per line, unchanged."
        ),
    )
    parser.add_argument("--watchlist", required=True, type=Path, help="Path to the active watchlist YAML file")
    parser.add_argument("--state", required=True, type=Path, help="Path to the seen-items state JSON file")
    args = parser.parse_args()

    if not args.watchlist.is_file():
        print(f"error: watchlist file not found: {args.watchlist}", file=sys.stderr)
        return 1

    excludes_by_topic = load_topic_excludes(args.watchlist)
    seen_urls = load_seen_urls(args.state)

    survivors = 0
    dropped_seen = 0
    dropped_excluded = 0
    dropped_unknown = 0
    for lineno, raw_line in enumerate(sys.stdin, start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"error: stdin line {lineno}: invalid JSON: {exc}", file=sys.stderr)
            return 1

        topic_id = item.get("topic_id")
        url = item.get("url")
        if not topic_id or not url:
            print(f"warning: stdin line {lineno}: missing topic_id or url, skipping", file=sys.stderr)
            continue

        excludes = excludes_by_topic.get(topic_id)
        if excludes is None:
            print(f"warning: stdin line {lineno}: unknown topic_id '{topic_id}', skipping", file=sys.stderr)
            dropped_unknown += 1
            continue

        if url in seen_urls:
            dropped_seen += 1
            continue

        host = urlparse(url).hostname or ""
        if host_in_domains(host, excludes):
            dropped_excluded += 1
            continue

        print(json.dumps(item))
        survivors += 1

    print(
        "diff_state: "
        f"{survivors} survivor(s); "
        f"dropped {dropped_seen} seen, {dropped_excluded} excluded-domain, {dropped_unknown} unknown-topic item(s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
