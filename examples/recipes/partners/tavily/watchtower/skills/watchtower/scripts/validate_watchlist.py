#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fail-fast schema validator for watchtower watchlist YAML files.

Watchtower watchlists use a deliberately restricted YAML subset: a top-level
`watchlist:` name, a `topics:` list, and topic entries with required fields
(`id`, `query`, `why_it_matters`) plus optional fields (`seed_sources`,
`exclude_domains`, `lookback_days`). PyYAML is not part of the Python standard
library, so rather than take on a third-party dependency this validator reads
that restricted subset itself with a small line-based parser. It is not a
general-purpose YAML parser — do not point it at arbitrary YAML files.

Usage:
    python3 validate_watchlist.py <watchlist.yaml>

Exits non-zero with a message describing the first schema violation found.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_TOPIC_KEYS = ("id", "query", "why_it_matters")
OPTIONAL_TOPIC_KEYS = ("seed_sources", "exclude_domains", "lookback_days")
LIST_TOPIC_KEYS = {"seed_sources", "exclude_domains"}
ALL_TOPIC_KEYS = set(REQUIRED_TOPIC_KEYS) | set(OPTIONAL_TOPIC_KEYS)

_TOP_KEY_RE = re.compile(r"^(\w[\w-]*):\s*(.*)$")
_TOPIC_START_RE = re.compile(r"^\s*-\s*id:\s*(.+)$")
_TOPIC_FIELD_RE = re.compile(r"^\s+([\w-]+):\s*(.*)$")


class WatchlistError(ValueError):
    """Raised when a watchlist file cannot be parsed or violates the schema."""


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


def parse_watchlist(path: Path) -> dict:
    """Parse the restricted watchlist YAML subset into a plain dict.

    Returns {"watchlist": <name>, "topics": [<topic dict>, ...]}. Raises
    WatchlistError on any line that does not match the expected shape.
    """
    name: str | None = None
    topics: list[dict] = []
    current: dict | None = None

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        topic_start = _TOPIC_START_RE.match(line)
        if topic_start:
            if current is not None:
                topics.append(current)
            current = {"id": _strip_quotes(topic_start.group(1))}
            continue

        field = _TOPIC_FIELD_RE.match(line)
        if field and current is not None:
            key, value = field.group(1), field.group(2)
            if key not in ALL_TOPIC_KEYS:
                raise WatchlistError(f"{path}:{lineno}: unknown topic field '{key}'")
            if key in LIST_TOPIC_KEYS:
                current[key] = _parse_list(value)
            elif key == "lookback_days":
                current[key] = _strip_quotes(value)
            else:
                current[key] = _strip_quotes(value)
            continue

        top = _TOP_KEY_RE.match(line)
        if top:
            if current is not None:
                topics.append(current)
                current = None
            key, value = top.group(1), top.group(2)
            if key == "watchlist":
                name = _strip_quotes(value)
            elif key != "topics":
                raise WatchlistError(f"{path}:{lineno}: unknown top-level field '{key}'")
            continue

        raise WatchlistError(f"{path}:{lineno}: unrecognized line: {raw_line!r}")

    if current is not None:
        topics.append(current)

    if name is None:
        raise WatchlistError(f"{path}: missing top-level 'watchlist:' name")

    return {"watchlist": name, "topics": topics}


def validate(parsed: dict, source: str) -> None:
    """Raise WatchlistError on the first schema violation found."""
    topics = parsed.get("topics") or []
    if not topics:
        raise WatchlistError(f"{source}: 'topics' list is empty — at least one topic is required")

    seen_ids: set[str] = set()
    for index, topic in enumerate(topics):
        label = topic.get("id") or f"topics[{index}]"

        for key in REQUIRED_TOPIC_KEYS:
            if key not in topic or not topic[key]:
                raise WatchlistError(
                    f"{source}: topic '{label}' is missing required key '{key}'"
                )

        for key in LIST_TOPIC_KEYS:
            if key in topic and not isinstance(topic[key], list):
                raise WatchlistError(f"{source}: topic '{label}' field '{key}' must be a list")

        if "lookback_days" in topic:
            try:
                lookback_days = int(topic["lookback_days"])
            except (TypeError, ValueError):
                raise WatchlistError(
                    f"{source}: topic '{label}' field 'lookback_days' must be a positive integer"
                ) from None
            if lookback_days <= 0:
                raise WatchlistError(
                    f"{source}: topic '{label}' field 'lookback_days' must be a positive integer"
                )

        if topic["id"] in seen_ids:
            raise WatchlistError(f"{source}: duplicate topic id '{topic['id']}'")
        seen_ids.add(topic["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a watchtower watchlist YAML file against the required schema.",
    )
    parser.add_argument(
        "watchlist",
        type=Path,
        help="Path to a watchlist YAML file (e.g. watchlists/regulatory.yaml)",
    )
    args = parser.parse_args()

    if not args.watchlist.is_file():
        print(f"error: watchlist file not found: {args.watchlist}", file=sys.stderr)
        return 1

    try:
        parsed = parse_watchlist(args.watchlist)
        validate(parsed, str(args.watchlist))
    except WatchlistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"ok: {args.watchlist} — watchlist '{parsed['watchlist']}' "
        f"with {len(parsed['topics'])} topic(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
