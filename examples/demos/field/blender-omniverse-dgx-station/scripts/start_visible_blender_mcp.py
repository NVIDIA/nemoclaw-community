#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Load Blender MCP into the current visible Blender process and start it."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import bpy


def _load_addon_namespace(addon_path: Path) -> dict:
    module_name = "blendermcp_addon_embedded"
    module = types.ModuleType(module_name)
    module.__file__ = str(addon_path)
    sys.modules[module_name] = module
    namespace = module.__dict__
    source = addon_path.read_text(encoding="utf-8")
    exec(compile(source, str(addon_path), "exec"), namespace)
    return namespace


def main() -> None:
    addon_value = os.environ.get("BLENDER_MCP_ADDON")
    if not addon_value:
        raise SystemExit("BLENDER_MCP_ADDON must point to blender_mcp_addon.py")

    addon_path = Path(addon_value).expanduser()
    host = os.environ.get("BLENDER_MCP_HOST", "localhost")
    port = int(os.environ.get("BLENDER_MCP_PORT", "9876"))

    if not addon_path.exists():
        raise SystemExit(f"Blender MCP add-on not found: {addon_path}")

    namespace = _load_addon_namespace(addon_path)
    register = namespace["register"]
    server_class = namespace["BlenderMCPServer"]

    try:
        register()
    except ValueError as exc:
        if "already registered" not in str(exc):
            raise

    scene = bpy.context.scene
    scene.blendermcp_port = port
    render_engine = os.environ.get("BLENDER_RENDER_ENGINE", "OVRTX_EXAMPLE")
    try:
        scene.render.engine = render_engine
    except TypeError as exc:
        raise SystemExit(
            f"Blender render engine {render_engine!r} is unavailable; "
            "verify that the OV add-on is installed and enabled"
        ) from exc

    current = getattr(bpy.types, "blendermcp_server", None)
    if current and not _server_matches(current, host, port):
        current.stop()
        bpy.types.blendermcp_server = None
        current = None

    if not current:
        current = server_class(host=host, port=port)
        bpy.types.blendermcp_server = current

    if not current.running:
        current.start()

    scene.blendermcp_server_running = current.running
    if not current.running:
        raise SystemExit(f"Blender MCP server did not start on {host}:{port}")

    print(
        f"BLENDER_MCP_READY host={host} port={port} render_engine={scene.render.engine}",
        flush=True,
    )


def _server_matches(server: object, host: str, port: int) -> bool:
    server_port = getattr(server, "port", port)
    server_host = getattr(server, "host", host)
    return server_port == port and _same_loopback_host(str(server_host), host)


def _same_loopback_host(left: str, right: str) -> bool:
    loopback = {"localhost", "127.0.0.1", "::1"}
    return left == right or (left in loopback and right in loopback)


if __name__ == "__main__":
    main()
