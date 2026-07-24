#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small stdio MCP server exposing bounded host-Blender workflow tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
from typing import Any


SERVER_NAME = "blender-workflow"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
RECEIPT_PREFIX = "BLENDER_WORKFLOW_RECEIPT="
HELPER = Path(
    os.environ.get(
        "BLENDER_WORKFLOW_HELPER",
        str(Path.home() / ".local/share/nemoclaw-blender/blender_workflow_helper.py"),
    )
).expanduser().resolve()
BLENDER_HOST = os.environ.get("BLENDER_WORKFLOW_BLENDER_HOST", "127.0.0.1")
BLENDER_PORT = int(os.environ.get("BLENDER_WORKFLOW_BLENDER_PORT", "9876"))
TIMEOUT = int(os.environ.get("BLENDER_WORKFLOW_TIMEOUT", "900"))


def _roots(name: str, default: str) -> list[Path]:
    value = os.environ.get(name, default)
    return [Path(item).expanduser().resolve() for item in value.split(":") if item]


READ_ROOTS = _roots("BLENDER_WORKFLOW_READ_ROOTS", str(Path.home() / "work"))
WRITE_ROOTS = _roots(
    "BLENDER_WORKFLOW_WRITE_ROOTS",
    str(Path.home() / "work/ov-blender-hermes-demo/out"),
)


TOOLS: list[dict[str, object]] = [
    {
        "name": "capability_probe",
        "description": (
            "Probe live host Blender, USD, OVRTX, and SimReady capabilities. "
            "Use this before claiming a schema or runtime is supported."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "scene_inventory",
        "description": (
            "Inventory the active host Blender scene. Returns compact counts and can write "
            "the detailed inventory to a task-owned host JSON path. Call with optional "
            "output_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Optional absolute host JSON path under an allowed output root.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "usd_export",
        "description": (
            "Export the active host Blender scene to a task-owned USD file and prove the "
            "source .blend hash is unchanged. Call with required output_path and optional "
            "selected_objects_only; do not rename output_path to path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Absolute host .usd, .usda, or .usdc path under an allowed output root.",
                },
                "selected_objects_only": {"type": "boolean", "default": False},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usd_inspect",
        "description": (
            "Open and inspect an exact host USD stage with Blender's installed pxr runtime. "
            "Returns compact stage counts and can write full prim/dependency details to JSON. "
            "Call with required input_path and optional output_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Absolute host USD path under an allowed read root.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional absolute host JSON path under an allowed output root.",
                },
            },
            "required": ["input_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "artifact_receipts",
        "description": (
            "Verify up to 50 exact host artifact paths and return presence, byte size, and "
            "SHA-256. Call with paths as an array of absolute host paths. A file must appear "
            "here before it may be reported as created."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {"type": "string"},
                }
            },
            "required": ["paths"],
            "additionalProperties": False,
        },
    },
]


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _validate_path(value: object, roots: list[Path], label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{label} must be an absolute host path")
    path = Path(value).expanduser().resolve()
    if not _under(path, roots):
        allowed = ", ".join(str(root) for root in roots)
        raise ValueError(f"{label} is outside the allowed roots: {allowed}")
    return str(path)


def _validated_request(name: str, arguments: object) -> dict[str, object]:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    request: dict[str, object] = {"action": name}
    if name == "capability_probe":
        return request
    if name == "scene_inventory":
        if arguments.get("output_path"):
            request["output_path"] = _validate_path(
                arguments["output_path"], WRITE_ROOTS, "output_path"
            )
        return request
    if name == "usd_export":
        request["output_path"] = _validate_path(
            arguments.get("output_path"), WRITE_ROOTS, "output_path"
        )
        request["selected_objects_only"] = bool(
            arguments.get("selected_objects_only", False)
        )
        return request
    if name == "usd_inspect":
        request["input_path"] = _validate_path(
            arguments.get("input_path"), READ_ROOTS, "input_path"
        )
        if arguments.get("output_path"):
            request["output_path"] = _validate_path(
                arguments["output_path"], WRITE_ROOTS, "output_path"
            )
        return request
    if name == "artifact_receipts":
        values = arguments.get("paths")
        if not isinstance(values, list) or not 1 <= len(values) <= 50:
            raise ValueError("paths must contain between 1 and 50 host paths")
        request["paths"] = [_validate_path(value, READ_ROOTS, "path") for value in values]
        return request
    raise ValueError(f"unknown tool: {name}")


def _blender_response(code: str) -> dict[str, object]:
    request = {"type": "execute_code", "params": {"code": code}}
    data = json.dumps(request).encode("utf-8")
    with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=10) as client:
        client.sendall(data)
        client.settimeout(TIMEOUT)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = client.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            try:
                value = json.loads(b"".join(chunks).decode("utf-8"))
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    if not chunks:
        raise RuntimeError(f"no response from host Blender at {BLENDER_HOST}:{BLENDER_PORT}")
    value = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("host Blender returned a non-object response")
    return value


def _call_blender(request: dict[str, object]) -> dict[str, object]:
    if not HELPER.is_file():
        raise RuntimeError(f"host workflow helper is unavailable: {HELPER}")
    code = (
        "import runpy;"
        f"runpy.run_path({str(HELPER)!r}, init_globals={{'BLENDER_WORKFLOW_REQUEST': {request!r}}})"
    )
    response = _blender_response(code)
    if response.get("status") != "success":
        raise RuntimeError(f"Blender MCP execution failed: {response}")
    result = response.get("result")
    payload = str(result.get("result", "")) if isinstance(result, dict) else ""
    for line in reversed(payload.splitlines()):
        if line.startswith(RECEIPT_PREFIX):
            receipt = json.loads(line[len(RECEIPT_PREFIX) :])
            if isinstance(receipt, dict):
                return receipt
    raise RuntimeError("host Blender returned no workflow receipt")


def _result(request_id: object, value: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _handle(message: dict[str, object]) -> dict[str, object] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            return _error(request_id, -32602, "tools/call requires object params")
        name = params.get("name")
        if not isinstance(name, str):
            return _error(request_id, -32602, "tool name must be a string")
        try:
            request = _validated_request(name, params.get("arguments", {}))
        except ValueError as error:
            payload = {
                "status": "invalid_arguments",
                "tool": name,
                "error_type": type(error).__name__,
                "error": str(error),
                "recovery": "Call tool_describe, correct the named arguments, and retry once.",
            }
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        }
                    ],
                    # Hermes treats MCP isError responses as connectivity failures and opens
                    # a circuit breaker. Invalid arguments are repairable, not an outage.
                    "isError": False,
                },
            )
        try:
            receipt = _call_blender(request)
            is_error = receipt.get("status") != "pass"
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                        }
                    ],
                    "isError": is_error,
                },
            )
        except Exception as error:
            payload = {
                "status": "blocked",
                "tool": name,
                "error_type": type(error).__name__,
                "error": str(error),
            }
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        }
                    ],
                    "isError": True,
                },
            )
    if request_id is None:
        return None
    return _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("MCP message must be an object")
            response = _handle(message)
        except Exception as error:
            response = _error(None, -32700, f"invalid request: {error}")
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
