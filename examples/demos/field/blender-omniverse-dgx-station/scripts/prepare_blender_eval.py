#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prepare or restore a task-owned Blender scene copy over Blender MCP."""

from __future__ import annotations

import argparse
import json
import socket
import sys


PREPARE_CODE = r'''
import hashlib
import json
from pathlib import Path
import bpy

source = Path(bpy.data.filepath).resolve()
output = Path(__OUTPUT__).expanduser().resolve()
if not source.is_file():
    raise RuntimeError("the active Blender scene has no readable source file")
if source == output:
    raise RuntimeError("evaluation output must differ from the active source scene")

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

source_before = sha256(source)
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
result = {
    "status": "pass",
    "source": str(source),
    "source_sha256_before": source_before,
    "source_sha256_after": sha256(source),
    "working_copy": str(output),
    "working_copy_sha256": sha256(output),
    "active_scene": bpy.data.filepath,
}
print("BLENDER_EVAL_RECEIPT=" + json.dumps(result, sort_keys=True))
'''

RESTORE_CODE = r'''
import hashlib
import json
from pathlib import Path
import bpy

source = Path(__SOURCE__).expanduser().resolve()
if not source.is_file():
    raise RuntimeError(f"source scene is unavailable: {source}")

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

source_hash = sha256(source)
bpy.ops.wm.open_mainfile(filepath=str(source))
result = {
    "status": "pass",
    "source": str(source),
    "source_sha256": source_hash,
    "active_scene": bpy.data.filepath,
}
print("BLENDER_EVAL_RECEIPT=" + json.dumps(result, sort_keys=True))
'''
PREFIX = "BLENDER_EVAL_RECEIPT="


def _execute(host: str, port: int, code: str, timeout: int) -> dict[str, object]:
    request = {"type": "execute_code", "params": {"code": code}}
    with socket.create_connection((host, port), timeout=10) as client:
        client.sendall(json.dumps(request).encode("utf-8"))
        client.settimeout(timeout)
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
                return json.loads(b"".join(chunks).decode("utf-8"))
            except json.JSONDecodeError:
                continue
    if not chunks:
        raise SystemExit(f"no response from Blender MCP at {host}:{port}")
    return json.loads(b"".join(chunks).decode("utf-8"))


def _receipt(response: dict[str, object]) -> dict[str, object]:
    if response.get("status") != "success":
        raise SystemExit(json.dumps(response, indent=2))
    result = response.get("result")
    payload = str(result.get("result", "")) if isinstance(result, dict) else ""
    for line in reversed(payload.splitlines()):
        if line.startswith(PREFIX):
            value = json.loads(line[len(PREFIX) :])
            if isinstance(value, dict):
                return value
    raise SystemExit(f"Blender returned no evaluation receipt:\n{payload}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=9876)
    result.add_argument("--timeout", type=int, default=180)
    commands = result.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--source", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.action == "prepare":
        code = PREPARE_CODE.replace("__OUTPUT__", repr(args.output))
    else:
        code = RESTORE_CODE.replace("__SOURCE__", repr(args.source))
    receipt = _receipt(_execute(args.host, args.port, code, max(10, args.timeout)))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
