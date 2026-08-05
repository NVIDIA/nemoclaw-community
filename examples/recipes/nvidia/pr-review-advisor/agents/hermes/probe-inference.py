#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run a bounded, sessionless readiness probe through OpenShell inference."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

INFERENCE_URL = "https://inference.local/v1/chat/completions"
PROXY_TOKEN = "sk-OPENSHELL-PROXY-REWRITE"
MAX_RESPONSE_BYTES = 1_048_576
TIMEOUT_SECONDS = 30


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so the proxy token never leaves inference.local."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def read_bounded(response: Any) -> bytes:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(
            f"inference readiness response exceeds {MAX_RESPONSE_BYTES} bytes"
        )
    return raw


def validate_response(raw: bytes) -> None:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("inference readiness response is not valid JSON") from error
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("choices"), list)
        or not payload["choices"]
        or not isinstance(payload["choices"][0], dict)
    ):
        raise ValueError("inference readiness response has no completion choice")


def completion_token_field(model: str) -> str:
    """Match Hermes v0.18's token-limit field for current OpenAI model families."""

    model_tail = model.rsplit("/", 1)[-1].lower()
    if model_tail.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4")):
        return "max_completion_tokens"
    return "max_tokens"


def probe(model: str, opener: Any | None = None) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}", model):
        raise ValueError("model contains unsafe characters")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with OK.",
            }
        ],
        completion_token_field(model): 1,
        "stream": False,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        INFERENCE_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {PROXY_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    if opener is None:
        # OpenShell implements inference.local through the supervisor proxy
        # injected into the sandbox environment. Keep that proxy active while
        # rejecting redirects so the rewrite token stays on the fixed route.
        opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.getcode()
            if not isinstance(status, int) or not 200 <= status < 300:
                raise ValueError(
                    f"inference readiness probe returned unexpected HTTP {status}"
                )
            validate_response(read_bounded(response))
    except urllib.error.HTTPError as error:
        # Drain a bounded amount for connection reuse, but never expose provider
        # response content in host logs.
        try:
            read_bounded(error)
        except ValueError:
            pass
        raise ValueError(
            f"inference readiness probe returned HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ValueError("inference readiness probe could not reach the route") from error


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: probe-inference.py MODEL", file=sys.stderr)
        return 2
    try:
        probe(sys.argv[1])
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
