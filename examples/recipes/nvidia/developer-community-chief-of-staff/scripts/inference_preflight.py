#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate an OpenAI-compatible inference route before sandbox creation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

KEY_ENV = "NEMOCLAW_INFERENCE_PREFLIGHT_KEY"


@dataclass
class PreflightError(Exception):
    category: str
    detail: str
    exit_code: int

    def __str__(self) -> str:
        return f"Inference preflight failed ({self.category}): {self.detail}"


def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def completion_url(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PreflightError("endpoint", "endpoint must be an http(s) URL", 3)
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        raise PreflightError(
            "endpoint",
            "remote inference endpoints must use HTTPS; HTTP is allowed only for loopback hosts",
            3,
        )

    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, "")
    )


def display_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    hostname = parsed.hostname or "invalid-host"
    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit(
        (parsed.scheme, f"{hostname}{port}", parsed.path.rstrip("/"), "", "")
    )


def response_mentions_model(response_body: bytes) -> bool:
    try:
        payload = json.loads(response_body.decode("utf-8", errors="replace"))
        message = json.dumps(payload).lower()
    except (json.JSONDecodeError, UnicodeDecodeError):
        message = response_body.decode("utf-8", errors="replace").lower()
    return "model" in message and any(
        marker in message
        for marker in ("not found", "unknown", "unavailable", "does not exist", "access")
    )


def classify_http_error(error: urllib.error.HTTPError) -> PreflightError:
    body = error.read(16384)
    status = error.code
    if status in {401, 403}:
        return PreflightError(
            "authentication",
            f"provider rejected the credential (HTTP {status})",
            4,
        )
    if status in {400, 404} and response_mentions_model(body):
        return PreflightError(
            "model-access",
            f"configured model is unavailable or unauthorized (HTTP {status})",
            5,
        )
    if status == 404:
        return PreflightError(
            "endpoint",
            "OpenAI-compatible chat completions route was not found (HTTP 404)",
            3,
        )
    if status in {408, 409, 425, 429} or status >= 500:
        return PreflightError(
            "provider-availability",
            f"provider could not serve the preflight request (HTTP {status})",
            6,
        )
    return PreflightError(
        "provider-response",
        f"provider rejected the preflight request (HTTP {status})",
        6,
    )


def validate_completion_response(response_body: bytes) -> None:
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PreflightError(
            "provider-response",
            "provider returned a non-JSON success response",
            6,
        ) from None

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("choices"), list)
        or not payload["choices"]
    ):
        raise PreflightError(
            "provider-response",
            "provider response did not include a completion choice",
            6,
        )


def run_preflight(endpoint: str, model: str, key: str, timeout: float) -> None:
    if not key:
        raise PreflightError("configuration", "inference credential is missing", 2)
    if not model.strip():
        raise PreflightError("configuration", "NEMOCLAW_MODEL is empty", 2)
    if timeout <= 0:
        raise PreflightError("configuration", "timeout must be greater than zero", 2)

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 1,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        completion_url(endpoint),
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise PreflightError(
                    "provider-response",
                    f"unexpected HTTP status {response.status}",
                    6,
                )
            validate_completion_response(response.read(16384))
    except urllib.error.HTTPError as error:
        raise classify_http_error(error) from None
    except (TimeoutError, socket.timeout):
        raise PreflightError(
            "timeout",
            f"provider did not respond within {timeout:g} seconds",
            7,
        ) from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise PreflightError(
                "timeout",
                f"provider did not respond within {timeout:g} seconds",
                7,
            ) from None
        raise PreflightError(
            "endpoint",
            "provider endpoint is unreachable or its TLS certificate is invalid",
            3,
        ) from None
    except (ssl.SSLError, ConnectionError, OSError):
        raise PreflightError(
            "endpoint",
            "provider endpoint is unreachable or its TLS certificate is invalid",
            3,
        ) from None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_preflight(
            endpoint=args.endpoint,
            model=args.model,
            key=os.environ.get(KEY_ENV, ""),
            timeout=args.timeout,
        )
    except PreflightError as error:
        print(error, file=sys.stderr)
        return error.exit_code

    print(
        "Inference preflight passed: "
        f"model={args.model} endpoint={display_endpoint(args.endpoint)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
