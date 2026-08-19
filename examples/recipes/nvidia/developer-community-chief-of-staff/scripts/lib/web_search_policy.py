#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage the optional, search-only Tavily network policy."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from .configuration import ConfigurationError
except ImportError:
    from configuration import ConfigurationError


POLICY_MARKER = "  # __TAVILY_WEB_SEARCH_POLICY__"
TAVILY_POLICY = """  tavily_web_search:
    name: tavily-web-search
    endpoints:
    - host: api.tavily.com
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      request_body_credential_rewrite: true
      rules:
      - allow: { method: POST, path: /search }
    binaries:
    - path: /opt/hermes/.venv/bin/python"""


def render_policy(template: str, *, enabled: bool) -> str:
    if template.count(POLICY_MARKER) != 1:
        raise ConfigurationError(
            "policy template must contain one Tavily web-search marker"
        )
    return template.replace(POLICY_MARKER, TAVILY_POLICY if enabled else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        template = args.template.read_text(encoding="utf-8")
        rendered = render_policy(
            template, enabled=bool(os.environ.get("TAVILY_API_KEY"))
        )
        args.output.write_text(rendered, encoding="utf-8")
        return 0
    except (ConfigurationError, OSError) as error:
        print(f"Web-search policy staging failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
