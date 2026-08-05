#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded host-side Blender and USD operations with compact receipts."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import bpy


PREFIX = "BLENDER_WORKFLOW_RECEIPT="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_receipt(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "status": "missing"}
    return {
        "path": str(path),
        "status": "present",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_json(path_value: object, payload: object) -> dict[str, object] | None:
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _file_receipt(path)


def _capability_probe() -> dict[str, object]:
    render_engines: list[str] = []
    try:
        engine = bpy.types.RenderSettings.bl_rna.properties["engine"]
        render_engines = sorted(item.identifier for item in engine.enum_items)
    except (KeyError, TypeError):
        pass

    addons = sorted(bpy.context.preferences.addons.keys())
    simready_addons = [name for name in addons if "simready" in name.casefold()]
    simready_operator_modules = sorted(
        name for name in dir(bpy.ops) if "simready" in name.casefold()
    )
    pxr_modules: dict[str, bool] = {}
    for name in ("Usd", "UsdGeom", "UsdShade", "UsdPhysics", "UsdUtils"):
        try:
            __import__(f"pxr.{name}", fromlist=[name])
            pxr_modules[name] = True
        except ImportError:
            pxr_modules[name] = False

    return {
        "blender_version": bpy.app.version_string,
        "scene_path": bpy.data.filepath or None,
        "usd_export_operator": hasattr(bpy.ops.wm, "usd_export"),
        "pxr_modules": pxr_modules,
        "render_engines": render_engines,
        "ovrtx_available": "OVRTX_EXAMPLE" in render_engines,
        "simready_addons": simready_addons,
        "simready_operator_modules": simready_operator_modules,
        "simready_authoring_supported": bool(
            simready_addons and simready_operator_modules
        ),
        "limitations": (
            []
            if simready_addons and simready_operator_modules
            else [
                "No enabled SimReady add-on with a discoverable operator module was "
                "detected. Do not invent SimReady or nonvisual-material schema fields; "
                "report that authoring milestone as blocked."
            ]
        ),
    }


def _external_dependencies() -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = []
    for library in bpy.data.libraries:
        dependencies.append(
            {"kind": "library", "name": library.name, "path": library.filepath}
        )
    for image in bpy.data.images:
        if image.packed_file or not image.filepath:
            continue
        dependencies.append(
            {"kind": "image", "name": image.name, "path": image.filepath}
        )
    dependencies.sort(key=lambda item: (str(item["kind"]), str(item["name"])))
    return dependencies


def _scene_inventory(request: dict[str, object]) -> dict[str, object]:
    scene = bpy.context.scene
    objects = []
    for obj in sorted(scene.objects, key=lambda item: item.name):
        objects.append(
            {
                "name": obj.name,
                "type": obj.type,
                "parent": obj.parent.name if obj.parent else None,
                "collections": sorted(collection.name for collection in obj.users_collection),
                "materials": sorted(
                    slot.material.name for slot in obj.material_slots if slot.material
                ),
                "rigid_body": obj.rigid_body.type if obj.rigid_body else None,
            }
        )

    unit_settings = scene.unit_settings
    dependencies = _external_dependencies()
    inventory = {
        "scene": scene.name,
        "scene_path": bpy.data.filepath or None,
        "object_count": len(objects),
        "object_types": dict(sorted(Counter(item["type"] for item in objects).items())),
        "objects": objects,
        "collection_count": len(bpy.data.collections),
        "collections": sorted(collection.name for collection in bpy.data.collections),
        "material_count": len(bpy.data.materials),
        "materials": sorted(material.name for material in bpy.data.materials),
        "camera": scene.camera.name if scene.camera else None,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "units": {
            "system": unit_settings.system,
            "scale_length": unit_settings.scale_length,
            "length_unit": unit_settings.length_unit,
        },
        "up_axis_assumption": "Z",
        "external_dependencies": dependencies,
        "rigid_body_count": sum(1 for item in objects if item["rigid_body"]),
        "blender_version": bpy.app.version_string,
    }
    artifact = _write_json(request.get("output_path"), inventory)
    return {
        "scene": inventory["scene"],
        "scene_path": inventory["scene_path"],
        "object_count": inventory["object_count"],
        "object_types": inventory["object_types"],
        "collection_count": inventory["collection_count"],
        "material_count": inventory["material_count"],
        "camera": inventory["camera"],
        "units": inventory["units"],
        "up_axis_assumption": inventory["up_axis_assumption"],
        "external_dependency_count": len(dependencies),
        "rigid_body_count": inventory["rigid_body_count"],
        "inventory_artifact": artifact,
    }


def _operator_parameters(operator: Any) -> set[str]:
    return {
        item.identifier
        for item in operator.get_rna_type().properties
        if item.identifier != "rna_type"
    }


def _usd_export(request: dict[str, object]) -> dict[str, object]:
    output = Path(str(request.get("output_path") or "")).expanduser().resolve()
    if output.suffix.casefold() not in {".usd", ".usda", ".usdc"}:
        raise ValueError("output_path must end in .usd, .usda, or .usdc")
    source = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if source is None or not source.is_file():
        raise RuntimeError("the active Blender scene has no readable source file")
    source_hash_before = _sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    available = _operator_parameters(bpy.ops.wm.usd_export)
    desired: dict[str, object] = {
        "filepath": str(output),
        "selected_objects_only": bool(request.get("selected_objects_only", False)),
        "export_materials": True,
        "export_textures": True,
        "relative_paths": True,
        "overwrite_textures": False,
    }
    options = {name: value for name, value in desired.items() if name in available}
    result = bpy.ops.wm.usd_export(**options)
    if "FINISHED" not in result:
        raise RuntimeError(f"USD export did not finish: {sorted(result)}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"USD export produced no non-empty file: {output}")

    source_hash_after = _sha256(source)
    return {
        "source_scene": str(source),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_unchanged": source_hash_before == source_hash_after,
        "output": _file_receipt(output),
        "operator": "bpy.ops.wm.usd_export",
        "options": options,
    }


def _usd_dependencies(path: Path) -> dict[str, object]:
    from pxr import UsdUtils

    try:
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(path))
    except Exception as error:  # USD builds vary; keep inspection useful and honest.
        return {"status": "blocked", "error": f"{type(error).__name__}: {error}"}
    return {
        "status": "pass",
        "layers": sorted(str(getattr(layer, "realPath", "") or layer.identifier) for layer in layers),
        "assets": sorted(str(asset) for asset in assets),
        "unresolved": sorted(str(asset) for asset in unresolved),
    }


def _usd_inspect(request: dict[str, object]) -> dict[str, object]:
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

    path = Path(str(request.get("input_path") or "")).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"USD input is unavailable: {path}")
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise RuntimeError(f"USD stage did not open: {path}")

    prims = list(stage.TraverseAll())
    type_counts = Counter(prim.GetTypeName() or "<untyped>" for prim in prims)
    paths = sorted(str(prim.GetPath()) for prim in prims)
    materials = sorted(
        str(prim.GetPath()) for prim in prims if prim.IsA(UsdShade.Material)
    )
    meshes = sorted(str(prim.GetPath()) for prim in prims if prim.IsA(UsdGeom.Mesh))
    rigid_bodies = sorted(
        str(prim.GetPath())
        for prim in prims
        if prim.HasAPI(UsdPhysics.RigidBodyAPI)
    )
    colliders = sorted(
        str(prim.GetPath())
        for prim in prims
        if prim.HasAPI(UsdPhysics.CollisionAPI)
    )
    mass_prims = sorted(
        str(prim.GetPath()) for prim in prims if prim.HasAPI(UsdPhysics.MassAPI)
    )
    default_prim = stage.GetDefaultPrim()
    detail = {
        "input": _file_receipt(path),
        "default_prim": str(default_prim.GetPath()) if default_prim else None,
        "up_axis": UsdGeom.GetStageUpAxis(stage),
        "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
        "start_time_code": stage.GetStartTimeCode(),
        "end_time_code": stage.GetEndTimeCode(),
        "time_codes_per_second": stage.GetTimeCodesPerSecond(),
        "prim_count": len(prims),
        "type_counts": dict(sorted(type_counts.items())),
        "prim_paths": paths,
        "mesh_paths": meshes,
        "material_paths": materials,
        "rigid_body_paths": rigid_bodies,
        "collider_paths": colliders,
        "mass_api_paths": mass_prims,
        "dependencies": _usd_dependencies(path),
        "layer_stack": [layer.identifier for layer in stage.GetLayerStack()],
    }
    artifact = _write_json(request.get("output_path"), detail)
    return {
        "input": detail["input"],
        "default_prim": detail["default_prim"],
        "up_axis": detail["up_axis"],
        "meters_per_unit": detail["meters_per_unit"],
        "prim_count": detail["prim_count"],
        "type_counts": detail["type_counts"],
        "mesh_count": len(meshes),
        "material_count": len(materials),
        "rigid_body_count": len(rigid_bodies),
        "collider_count": len(colliders),
        "mass_api_count": len(mass_prims),
        "dependency_status": detail["dependencies"],
        "inspection_artifact": artifact,
    }


def _artifact_receipts(request: dict[str, object]) -> dict[str, object]:
    values = request.get("paths")
    if not isinstance(values, list) or not values:
        raise ValueError("paths must be a non-empty list")
    if len(values) > 50:
        raise ValueError("at most 50 artifact paths may be verified at once")
    receipts = [_file_receipt(Path(str(value)).expanduser().resolve()) for value in values]
    return {
        "artifacts": receipts,
        "present_count": sum(item["status"] == "present" for item in receipts),
        "missing_count": sum(item["status"] == "missing" for item in receipts),
        "all_present": all(item["status"] == "present" for item in receipts),
    }


def _run(request: dict[str, object]) -> dict[str, object]:
    action = str(request.get("action") or "capability_probe")
    handlers = {
        "capability_probe": lambda _request: _capability_probe(),
        "scene_inventory": _scene_inventory,
        "usd_export": _usd_export,
        "usd_inspect": _usd_inspect,
        "artifact_receipts": _artifact_receipts,
    }
    if action not in handlers:
        raise ValueError(f"unsupported action: {action}")
    return {
        "status": "pass",
        "action": action,
        "execution_surface": "host_blender",
        "result": handlers[action](request),
    }


def main() -> None:
    request = globals().get("BLENDER_WORKFLOW_REQUEST", {"action": "capability_probe"})
    try:
        result = _run(dict(request))
    except Exception as error:
        result = {
            "status": "blocked",
            "action": str(dict(request).get("action") or "unknown"),
            "execution_surface": "host_blender",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    print(PREFIX + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ in {"__main__", "<run_path>"}:
    main()
