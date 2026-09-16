#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verify the result and saved file for the conference-research example."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import summarize_atof

SESSION_PREFIX = "session_id:"
URL_PATTERN = re.compile(r"https://[^\s)>\]]+")
Event = dict[str, Any]


def final_response(text: str) -> str:
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip().startswith(SESSION_PREFIX):
            response = "\n".join(lines[index + 1 :]).strip()
            if not response:
                raise ValueError("Hermes did not return a final response")
            return response
    raise ValueError("Hermes output does not contain a session identifier")


def normalize_answer(text: str) -> str:
    return text.strip().strip("`*_# ").strip()


def response_identifies_expected_name(text: str, expected_name: str) -> bool:
    return expected_name.casefold() in normalize_answer(text).casefold()


def is_expected_source_url(url: str, expected_prefix: str) -> bool:
    expected = urlsplit(expected_prefix)
    expected_path = expected.path.rstrip("/")
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == expected.hostname
        and (
            parsed.path.rstrip("/") == expected_path
            or parsed.path.startswith(f"{expected_path}/")
        )
    )


def official_source_urls(text: str, expected_prefix: str) -> set[str]:
    urls: set[str] = set()
    for match in URL_PATTERN.findall(text):
        url = match.rstrip(".,;:")
        if is_expected_source_url(url, expected_prefix):
            urls.add(url)
    return urls


def validate_report(
    text: str, *, expected_name: str, expected_source_prefix: str
) -> set[str]:
    required_facts = (expected_name, "June 29", "July 3", "2026", "San Diego")
    missing = [
        fact for fact in required_facts if fact.casefold() not in text.casefold()
    ]
    if missing:
        raise ValueError(f"verification report is missing: {', '.join(missing)}")

    urls = official_source_urls(text, expected_source_prefix)
    if not urls:
        raise ValueError(
            "verification report does not cite the expected official source"
        )
    return urls


def tool_data(event: Event) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def validate_research_trace(
    events: list[Event],
    *,
    expected_read_path: str,
    expected_write_path: str,
    expected_source_prefix: str,
) -> None:
    successful_starts = summarize_atof.successful_tool_start_events(events)

    def reads_expected_input(event: Event) -> bool:
        return (
            event.get("name") == "read_file"
            and tool_data(event).get("path") == expected_read_path
        )

    def searches_web(event: Event) -> bool:
        return event.get("name") == "web_search"

    def extracts_expected_source(event: Event) -> bool:
        urls = tool_data(event).get("urls")
        return event.get("name") == "web_extract" and isinstance(urls, list) and any(
            isinstance(url, str) and is_expected_source_url(url, expected_source_prefix)
            for url in urls
        )

    def writes_expected_report(event: Event) -> bool:
        return (
            event.get("name") == "write_file"
            and tool_data(event).get("path") == expected_write_path
        )

    required_path: list[tuple[str, Callable[[Event], bool]]] = [
        (f"read_file({expected_read_path})", reads_expected_input),
        ("web_search", searches_web),
        (f"web_extract({expected_source_prefix})", extracts_expected_source),
        (f"write_file({expected_write_path})", writes_expected_report),
    ]
    next_step = 0
    for event in successful_starts:
        if required_path[next_step][1](event):
            next_step += 1
            if next_step == len(required_path):
                return

    missing_path = " -> ".join(label for label, _ in required_path[next_step:])
    raise ValueError(
        f"trace is missing the required successful tool path: {missing_path}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the Hermes conference-research result."
    )
    parser.add_argument("response", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--expected-source-prefix", required=True)
    parser.add_argument("--expected-read-path", required=True)
    parser.add_argument("--expected-write-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        response = final_response(args.response.read_text(encoding="utf-8"))
        if not response_identifies_expected_name(response, args.expected_name):
            raise ValueError(
                f"final response must identify {args.expected_name!r}; found {response!r}"
            )
        report = args.report.read_text(encoding="utf-8")
        urls = validate_report(
            report,
            expected_name=args.expected_name,
            expected_source_prefix=args.expected_source_prefix,
        )
        validate_research_trace(
            summarize_atof.load_events(args.trace),
            expected_read_path=args.expected_read_path,
            expected_write_path=args.expected_write_path,
            expected_source_prefix=args.expected_source_prefix,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    noun = "source" if len(urls) == 1 else "sources"
    print(
        f"Conference result verified: {args.expected_name} "
        f"({len(urls)} official {noun})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
