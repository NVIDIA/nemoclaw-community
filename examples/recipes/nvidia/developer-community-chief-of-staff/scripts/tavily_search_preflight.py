#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate a Tavily API key with one bounded search request."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import BinaryIO

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PLACEHOLDER_PREFIX = "openshell:resolve:env:"


class TavilyPreflightError(RuntimeError):
    """A bounded Tavily configuration check failed."""


UrlOpen = Callable[..., BinaryIO]


def validate_host_key(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise TavilyPreflightError("Tavily API key is not configured")
    if key != api_key:
        raise TavilyPreflightError(
            "Tavily API key must not contain surrounding whitespace"
        )
    if key.startswith(PLACEHOLDER_PREFIX):
        raise TavilyPreflightError(
            "the host configuration must contain the Tavily API key, "
            "not an OpenShell placeholder"
        )
    if any(character in key for character in "\r\n\x00"):
        raise TavilyPreflightError(
            "Tavily API key contains an invalid control character"
        )
    return key


def run_preflight(
    api_key: str,
    timeout: float = 10.0,
    *,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> None:
    key = validate_host_key(api_key)
    payload = json.dumps(
        {
            "query": "NVIDIA NemoClaw",
            "max_results": 1,
            "include_answer": False,
            "include_raw_content": False,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "nemoclaw-community-tavily-preflight/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            body = response.read(1_048_577)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in {401, 403}:
            raise TavilyPreflightError(
                f"Tavily rejected the configured API key (HTTP {error.code})"
            ) from None
        raise TavilyPreflightError(
            f"Tavily search returned HTTP {error.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TavilyPreflightError("Tavily search could not be reached") from None

    if status != 200:
        raise TavilyPreflightError(f"Tavily search returned HTTP {status}")
    if len(body) > 1_048_576:
        raise TavilyPreflightError("Tavily search response exceeded 1 MiB")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TavilyPreflightError("Tavily search returned invalid JSON") from None
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise TavilyPreflightError(
            "Tavily search response did not contain a results list"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.timeout <= 60:
        print(
            "--timeout must be greater than 0 and at most 60 seconds",
            file=sys.stderr,
        )
        return 2
    try:
        run_preflight(os.environ.get("NEMOCLAW_TAVILY_PREFLIGHT_KEY", ""), args.timeout)
    except TavilyPreflightError as error:
        print(f"Tavily web-search preflight failed: {error}", file=sys.stderr)
        return 1
    print("Tavily web-search preflight passed (credential value redacted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
