#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patch OVRTX scene export so Blender final render has UI context.

Some current OVRTX add-on builds call bpy.ops.wm.usd_export from Blender's
render engine path with only ``scene`` in the context override. Blender 5.1 can
reject that call with:

    Operator bpy.ops.wm.usd_export.poll() failed, context is incorrect

This helper patches source and installed add-on copies in place until the same
fix is available in the released artifact.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


HELPER = '''
@contextmanager
def _usd_export_context(module: Any, scene: Any) -> Any:
    context = getattr(module, "context", None)
    if context is None:
        raise SceneGenerationError("Blender context is unavailable for scene generation")

    override: dict[str, Any] = {"scene": scene}
    window = getattr(context, "window", None)
    if window is None:
        window_manager = getattr(context, "window_manager", None)
        windows = tuple(getattr(window_manager, "windows", ()) or ())
        window = windows[0] if windows else None
    if window is not None:
        override["window"] = window

    screen = (
        getattr(window, "screen", None)
        if window is not None
        else getattr(context, "screen", None)
    )
    if screen is not None:
        override["screen"] = screen

    area = getattr(context, "area", None)
    if area is None and screen is not None:
        areas = tuple(getattr(screen, "areas", ()) or ())
        area = next((candidate for candidate in areas if candidate.type == "VIEW_3D"), None)
        if area is None and areas:
            area = areas[0]
    if area is not None:
        override["area"] = area

    region = getattr(context, "region", None)
    if region is None and area is not None:
        region = next(
            (candidate for candidate in getattr(area, "regions", ()) if candidate.type == "WINDOW"),
            None,
        )
    if region is not None:
        override["region"] = region

    view_layers = tuple(getattr(scene, "view_layers", ()) or ())
    if view_layers:
        current_view_layer = getattr(context, "view_layer", None)
        override["view_layer"] = (
            current_view_layer
            if current_view_layer is not None
            and any(layer is current_view_layer for layer in view_layers)
            else view_layers[0]
        )

    with context.temp_override(**override):
        yield

'''

OLD_EXPORT_CONTEXTS = (
    '''            _temporary_export_identities(scene),
            module.context.temp_override(scene=scene),
            _temporary_particle_hair_curves(
''',
    '''            _temporary_export_identities(scene),
            context.temp_override(scene=scene),
            _temporary_particle_hair_curves(
''',
)

NEW_EXPORT_CONTEXT = '''            _temporary_export_identities(scene),
            _usd_export_context(module, scene),
            _temporary_particle_hair_curves(
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, help="ov-blender-example checkout")
    parser.add_argument(
        "--extension-package",
        type=Path,
        default=Path.home()
        / ".config/blender/5.1/extensions/user_default/ovrtx_blender_example/ovrtx_blender_example",
        help="installed ovrtx_blender_example package directory",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    if args.repo:
        targets.append(args.repo / "addon/ovrtx_blender_example/scene_generation.py")
    targets.append(args.extension_package / "scene_generation.py")

    failures = 0
    for target in targets:
        try:
            status = patch_file(target)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"error: {target}: {exc}", file=sys.stderr)
        else:
            print(f"{status}: {target}")

    return 1 if failures else 0


def patch_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)

    text = path.read_text(encoding="utf-8")
    changed = False

    if "def _usd_export_context(" not in text:
        if "from contextlib import contextmanager" not in text:
            raise RuntimeError("scene_generation.py no longer imports contextmanager")
        marker = "\ndef _stock_export("
        if marker not in text:
            raise RuntimeError("could not find _stock_export insertion point")
        text = text.replace(marker, "\n" + HELPER + marker.lstrip("\n"), 1)
        changed = True

    context_patched = False
    for old_export_context in OLD_EXPORT_CONTEXTS:
        if old_export_context in text:
            text = text.replace(old_export_context, NEW_EXPORT_CONTEXT, 1)
            changed = True
            context_patched = True
            break
    if not context_patched and NEW_EXPORT_CONTEXT not in text:
        raise RuntimeError("could not find export context call site")

    if changed:
        path.write_text(text, encoding="utf-8")
        return "patched"
    return "already patched"


if __name__ == "__main__":
    raise SystemExit(main())
