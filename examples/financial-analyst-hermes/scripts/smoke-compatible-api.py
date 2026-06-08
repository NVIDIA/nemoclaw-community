#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Smoke-test an OpenAI-compatible chat completions API."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_MODEL = "financial-assistant"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        dest="base_url",
        default=os.environ.get(
            "FINANCE_API_URL", os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
        ),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "FINANCE_MODEL", os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        ),
    )
    parser.add_argument("--env-file", default=os.environ.get("ENV_FILE", ""))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))

    api_key = os.environ.get("FINANCE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": "FINANCE_API_KEY or OPENAI_API_KEY is not set",
                },
                indent=2,
            )
        )
        return 2

    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise financial analyst. Do not provide investment advice.",
            },
            {
                "role": "user",
                "content": "In one sentence, define free cash flow yield.",
            },
        ],
        "temperature": 0.2,
        "max_tokens": 160,
    }
    req = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=args.timeout) as response:
        data = json.load(response)
    message = data.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    print(
        json.dumps(
            {
                "ok": True,
                "base_url": args.base_url,
                "model": args.model,
                "assistant_excerpt": content[:500],
                "reasoning_excerpt": reasoning[:500],
            },
            indent=2,
        )
    )
    return 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                indent=2,
            )
        )
        raise SystemExit(1)
