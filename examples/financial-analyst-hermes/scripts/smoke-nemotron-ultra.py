#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Smoke-test NVIDIA-hosted Nemotron Ultra through the build.nvidia.com endpoint."""

from __future__ import annotations

import json
import os
import sys
import urllib.request


ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


def main() -> int:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print(json.dumps({"ok": False, "message": "NVIDIA_API_KEY is not set"}, indent=2))
        return 2

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise financial analyst. Do not provide investment advice.",
            },
            {"role": "user", "content": "In one sentence, define free cash flow yield."},
        ],
        "temperature": 0.2,
        "max_tokens": 80,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.load(response)
    message = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(json.dumps({"ok": True, "model": MODEL, "assistant_excerpt": message[:500]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, indent=2))
        raise SystemExit(1)
