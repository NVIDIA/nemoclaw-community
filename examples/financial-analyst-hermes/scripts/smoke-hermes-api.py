#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Smoke-test a Hermes OpenAI-compatible API endpoint."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request


def request_json(
    url: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    token: str | None = None,
    timeout: int = 180,
) -> dict[str, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        dest="base_url",
        default=os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642/v1"),
    )
    parser.add_argument("--token", default=os.environ.get("HERMES_API_KEY", ""))
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "FINANCE_MODEL", os.environ.get("HERMES_MODEL", "financial-assistant")
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=int(os.environ.get("HERMES_TIMEOUT", "180"))
    )
    args = parser.parse_args()

    root = args.base_url.rsplit("/v1", 1)[0].rstrip("/")
    health = request_json(
        f"{root}/health", token=args.token or None, timeout=args.timeout
    )
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise financial analyst. Do not provide investment advice.",
            },
            {
                "role": "user",
                "content": "Give me a three-bullet checklist for reviewing NVDA before earnings.",
            },
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }
    completion = request_json(
        f"{args.base_url.rstrip('/')}/chat/completions",
        method="POST",
        payload=payload,
        token=args.token or None,
        timeout=args.timeout,
    )
    message = completion.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(
        json.dumps(
            {
                "ok": True,
                "health": health,
                "model": args.model,
                "assistant_excerpt": str(message)[:800],
            },
            indent=2,
        )
    )
    return 0


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
