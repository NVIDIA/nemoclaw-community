#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate a structured-tool inference route before sandbox creation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

KEY_ENV = "NEMOCLAW_INFERENCE_PREFLIGHT_KEY"
TOOL_NAME = "nemoclaw_preflight"
TOOL_ARGUMENTS = {"value": "ready"}
TOOL_MARKERS = ("<|call|>", "<|tool_call|>", "<tool_call>", "</tool_call>")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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


def _text_contains_tool_json(content: str) -> bool:
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    return bool({"name", "arguments", "function", "tool_calls"} & value.keys())


def validate_tool_response(response_body: bytes) -> None:
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PreflightError(
            "tool-protocol",
            "provider returned a non-JSON success response",
            6,
        ) from None

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise PreflightError(
            "tool-protocol",
            "provider response did not include a completion choice",
            6,
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise PreflightError(
            "tool-protocol",
            "provider response did not include an assistant message",
            6,
        )

    content = message.get("content")
    if isinstance(content, str) and any(marker in content for marker in TOOL_MARKERS):
        raise PreflightError(
            "tool-protocol",
            "provider leaked an internal tool-call marker as assistant text",
            6,
        )
    if isinstance(content, str) and _text_contains_tool_json(content):
        raise PreflightError(
            "tool-protocol",
            "provider returned tool-call JSON as assistant text",
            6,
        )

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise PreflightError(
            "tool-protocol",
            "provider did not return a structured tool call",
            6,
        )
    if len(tool_calls) != 1 or not isinstance(tool_calls[0], dict):
        raise PreflightError(
            "tool-protocol",
            "provider returned an unexpected number of tool calls",
            6,
        )

    tool_call = tool_calls[0]
    if tool_call.get("type") != "function":
        raise PreflightError(
            "tool-protocol",
            "provider returned a non-function tool call",
            6,
        )
    function = tool_call.get("function")
    if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
        raise PreflightError(
            "tool-protocol",
            "provider called a function other than the preflight tool",
            6,
        )
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise PreflightError(
            "tool-protocol",
            "provider returned non-string tool arguments",
            6,
        )
    try:
        parsed_arguments = json.loads(arguments)
    except json.JSONDecodeError:
        raise PreflightError(
            "tool-protocol",
            "provider returned malformed tool arguments",
            6,
        ) from None
    if parsed_arguments != TOOL_ARGUMENTS:
        raise PreflightError(
            "tool-protocol",
            "provider returned incorrect preflight tool arguments",
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
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Call {TOOL_NAME} exactly once with value set to ready. "
                        "Do not answer with ordinary text."
                    ),
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": "Confirm structured tool-call compatibility.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string", "enum": ["ready"]}
                            },
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
            "max_tokens": 64,
            "stream": False,
            "temperature": 0,
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
            validate_tool_response(response.read(65536))
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


def _find_route_value(route_text: str, key: str) -> str | None:
    clean = ANSI_ESCAPE.sub("", route_text)
    try:
        payload: Any = json.loads(clean)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        inference = payload.get("inference")
        if isinstance(inference, dict) and isinstance(inference.get(key), str):
            return inference[key]

    user_heading = re.search(
        r"^\s*(?:Gateway\s+)?Inference:\s*$", clean, re.I | re.M
    )
    if user_heading:
        clean = clean[user_heading.end() :]
        system_heading = re.search(
            r"^\s*System inference:\s*$", clean, re.I | re.M
        )
        if system_heading:
            clean = clean[: system_heading.start()]

    match = re.search(rf"^\s*{re.escape(key)}\s*:\s*(\S+)\s*$", clean, re.I | re.M)
    return match.group(1) if match else None


def validate_active_route(route_text: str, provider: str, model: str) -> None:
    active_provider = _find_route_value(route_text, "provider")
    active_model = _find_route_value(route_text, "model")
    if not active_provider or not active_model:
        raise PreflightError(
            "active-route",
            "could not read provider and model from openshell inference get",
            8,
        )
    if active_provider != provider or active_model != model:
        raise PreflightError(
            "active-route",
            "active OpenShell provider/model does not match the requested configuration",
            8,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--endpoint")
    target.add_argument("--provider")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.provider:
            validate_active_route(sys.stdin.read(), args.provider, args.model)
            print(
                "Active inference route verified: "
                f"provider={args.provider} model={args.model}"
            )
        else:
            run_preflight(
                endpoint=args.endpoint,
                model=args.model,
                key=os.environ.get(KEY_ENV, ""),
                timeout=args.timeout,
            )
            print(
                "Structured tool-call preflight passed: "
                f"model={args.model} endpoint={display_endpoint(args.endpoint)}"
            )
    except PreflightError as error:
        print(error, file=sys.stderr)
        return error.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
