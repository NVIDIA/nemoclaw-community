#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verify the visible Blender process sees the installed OVRTX runtime."""

from __future__ import annotations

import argparse
import json
import socket
import sys


BLENDER_CODE = r'''
import importlib
import json
from pathlib import Path
import time
import traceback

import bpy

wait_seconds = __WAIT_SECONDS__
result = {}

try:
    impl = importlib.import_module(
        "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example"
    )
    bundled_runtime = importlib.import_module(
        "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example.bundled_runtime"
    )
    runtime_services = importlib.import_module(
        "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example.runtime_services"
    )

    prefs = impl.get_addon_preferences()
    runtime = impl.runtime_bundle_status()
    root_value = (
        str(runtime.get("current_root") or "")
        if runtime.get("state") == "ready"
        else ""
    )
    defaults = bundled_runtime.defaults(root=Path(root_value) if root_value else None)

    if prefs is not None and root_value:
        prefs.worker_command = defaults.worker_command
        prefs.native_client_path = defaults.native_client_path
        prefs.native_client_module = bundled_runtime.DEFAULT_OVRTX_NATIVE_CLIENT_MODULE

    started = impl.start_runtime_services_async()
    deadline = time.monotonic() + max(0, wait_seconds)
    diagnostics = runtime_services.owner.diagnostics()
    while diagnostics.get("status") not in {"ready", "failed"} and time.monotonic() < deadline:
        time.sleep(0.5)
        diagnostics = runtime_services.owner.diagnostics()

    preflight = impl.preflight_preferences(prefs) if prefs is not None else None
    result = {
        "ok": bool(preflight and preflight.get("status") == "pass"),
        "addon_preferences_id": getattr(impl, "ADDON_PREFERENCES_ID", ""),
        "blend_file": bpy.data.filepath,
        "is_dirty": bool(bpy.data.is_dirty),
        "render_engine": bpy.context.scene.render.engine,
        "runtime": runtime,
        "started_async": started,
        "worker_command": getattr(prefs, "worker_command", "") if prefs else "",
        "native_client_path": getattr(prefs, "native_client_path", "") if prefs else "",
        "ovphysx_worker_command": defaults.ovphysx_worker_command,
        "runtime_services": diagnostics,
        "preflight": preflight,
    }
except Exception as exc:
    result = {
        "ok": False,
        "error": repr(exc),
        "traceback": traceback.format_exc(),
    }

print(json.dumps(result, indent=2, default=str))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Blender MCP TCP host")
    parser.add_argument("--port", type=int, default=9876, help="Blender MCP TCP port")
    parser.add_argument(
        "--wait",
        type=int,
        default=120,
        help="seconds to wait for OVRTX/OVPhysX runtime services",
    )
    args = parser.parse_args()

    code = BLENDER_CODE.replace("__WAIT_SECONDS__", str(max(0, int(args.wait))))
    response = _execute(args.host, args.port, code, timeout=max(10, args.wait + 10))
    if response.get("status") != "success":
        print(json.dumps(response, indent=2), file=sys.stderr)
        return 1

    payload = str(response.get("result", {}).get("result", "")).strip()
    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        print(payload)
        print("Blender returned non-JSON verification output", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


def _execute(host: str, port: int, code: str, *, timeout: int) -> dict[str, object]:
    command = {"type": "execute_code", "params": {"code": code}}
    data = json.dumps(command).encode("utf-8")
    with socket.create_connection((host, port), timeout=10) as client:
        client.sendall(data)
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


if __name__ == "__main__":
    raise SystemExit(main())
