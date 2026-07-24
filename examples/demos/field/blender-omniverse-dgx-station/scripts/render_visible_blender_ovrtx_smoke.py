#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run a one-sample OVRTX render through the visible Blender MCP process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys


BLENDER_CODE = r'''
import bpy
import json
import os
import traceback

output_path = __OUTPUT_PATH__
width = __WIDTH__
height = __HEIGHT__
samples = __SAMPLES__
reset_scene_generation = __RESET_SCENE_GENERATION__

try:
    reset_status = "not_requested"
    cleanup_status = {"status": "not_requested", "deleted": []}
    if reset_scene_generation:
        import importlib

        scene_generation_sessions = importlib.import_module(
            "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example.scene_generation_sessions"
        )
        scene_generation_sessions.close()
        reset_status = "closed"
        runtime_services = importlib.import_module(
            "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example.runtime_services"
        )
        ovrtx_runtime_client = importlib.import_module(
            "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example.ovrtx_runtime_client"
        )
        diagnostics = runtime_services.owner.diagnostics()
        endpoint = (
            diagnostics.get("health", {})
            .get("ovrtx", {})
            .get("endpoint", "127.0.0.1:50051")
        )
        bindings = ovrtx_runtime_client._bind_official_control_plane(  # noqa: SLF001
            {"endpoint": endpoint},
            "",
        )
        try:
            listed = dict(bindings.list_simulations({"limit": 100, "offset": 0}))
            simulations = [str(item) for item in listed.get("simulations", ()) if item]
            suffix = f"-{os.getpid()}"
            targets = [
                item
                for item in simulations
                if item.startswith("ovrtx-blender-") and item.endswith(suffix)
            ]
            deleted = []
            for simulation_id in targets:
                bindings.delete_simulation({"simulation_id": simulation_id})
                deleted.append(simulation_id)
            cleanup_status = {
                "status": "done",
                "endpoint": endpoint,
                "listed": simulations,
                "deleted": deleted,
            }
        finally:
            bindings.close()

    scene = bpy.context.scene
    if scene.camera is None:
        cameras = [obj for obj in scene.objects if getattr(obj, "type", "") == "CAMERA"]
        if cameras:
            scene.camera = cameras[0]

    scene.render.engine = "OVRTX_EXAMPLE"
    scene.render.filepath = output_path
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    if hasattr(scene, "ovrtx_example"):
        scene.ovrtx_example.min_samples = samples
        scene.ovrtx_example.max_samples = samples

    if os.path.exists(output_path):
        os.remove(output_path)

    bpy.ops.render.render(write_still=True)

    result = {
        "ok": os.path.exists(output_path) and os.path.getsize(output_path) > 0,
        "engine": scene.render.engine,
        "camera": getattr(scene.camera, "name", None),
        "output": output_path,
        "exists": os.path.exists(output_path),
        "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
        "scene_generation_reset": reset_status,
        "ovrtx_worker_cleanup": cleanup_status,
    }
except Exception as exc:
    result = {
        "ok": False,
        "error": repr(exc),
        "traceback": traceback.format_exc(),
        "engine": getattr(bpy.context.scene.render, "engine", None),
        "output": output_path,
        "exists": os.path.exists(output_path),
        "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
        "scene_generation_reset": locals().get("reset_status", "not_reached"),
        "ovrtx_worker_cleanup": locals().get("cleanup_status", "not_reached"),
    }

print(json.dumps(result))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Blender MCP TCP host")
    parser.add_argument("--port", type=int, default=9876, help="Blender MCP TCP port")
    parser.add_argument("--output", type=Path, required=True, help="PNG output path on host")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--no-reset-scene-generation",
        action="store_true",
        help="do not clear OVRTX scene-generation state before rendering",
    )
    args = parser.parse_args()

    code = (
        BLENDER_CODE.replace("__OUTPUT_PATH__", json.dumps(str(args.output)))
        .replace("__WIDTH__", str(max(1, int(args.width))))
        .replace("__HEIGHT__", str(max(1, int(args.height))))
        .replace("__SAMPLES__", str(max(1, int(args.samples))))
        .replace("__RESET_SCENE_GENERATION__", "False" if args.no_reset_scene_generation else "True")
    )
    response = _execute(args.host, args.port, code, timeout=max(30, args.timeout))
    if response.get("status") != "success":
        print(json.dumps(response, indent=2), file=sys.stderr)
        return 1

    payload = str(response.get("result", {}).get("result", "")).strip()
    result = _parse_payload(payload)
    if result is None:
        print(payload)
        print("Blender returned non-JSON render output", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


def _parse_payload(payload: str) -> dict[str, object] | None:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass
    for line in reversed(payload.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


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
