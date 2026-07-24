#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small host-side action dispatcher for Hermes, Blender, and native OVPhysX."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping


CONFIG_PATH = Path.home() / ".config" / "nemoclaw-blender" / "ovphysx-helper.json"
FIXTURE_SOURCE_KEY = "nemoclaw_ovphysx_fixture_source"
FIXTURE_TRANSFORMS_KEY = "nemoclaw_ovphysx_fixture_transforms"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _settings(request: Mapping[str, Any]) -> dict[str, Any]:
    config = _load_json(CONFIG_PATH)
    merged = dict(config)
    merged.update({key: value for key, value in request.items() if key != "action"})
    merged["body_prims"] = list(merged.get("body_prims") or [])
    if not merged["body_prims"]:
        raise ValueError("at least one body prim is required")
    return merged


def _compact_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    value = _load_json(path)
    return {"path": str(path), **value}


def _resolve_ovphysx_server(runtime_root: Path) -> Path:
    candidates = (
        runtime_root / "bin" / "ovphysx-bridge-server",
        runtime_root / "bin" / "ovphysx_grpc_server",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def _preflight(settings: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "ov_repo": Path(settings["ov_repo"]),
        "runtime_root": Path(settings["runtime_root"]),
        "fixture": Path(settings["fixture"]),
        "timeline_runner": Path(settings["timeline_runner"]),
        "ffmpeg": Path(settings.get("ffmpeg", shutil.which("ffmpeg") or "/usr/bin/ffmpeg")),
    }
    checks = {name: path.exists() for name, path in paths.items()}
    runtime_root = paths["runtime_root"]
    ovphysx_server = _resolve_ovphysx_server(runtime_root)
    checks.update(
        {
            "ovphysx_server": ovphysx_server.is_file(),
            "native_client_dir": (runtime_root / "native").is_dir(),
        }
    )
    addon = settings.get(
        "installed_addon_package",
        "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example",
    )
    diagnostics: dict[str, Any] = {"ovphysx_server": str(ovphysx_server)}
    try:
        bundled = __import__(f"{addon}.bundled_runtime", fromlist=["defaults"])
        services = __import__(f"{addon}.runtime_services", fromlist=["owner"])
        defaults = bundled.defaults()
        service_details = services.owner.diagnostics()
        diagnostics["bundled_runtime"] = {
            key: defaults[key]
            for key in ("root", "platform", "status")
            if isinstance(defaults, Mapping) and key in defaults
        }
        diagnostics["runtime_services"] = {
            "status": service_details.get("status"),
            "root": service_details.get("root"),
            **{
                name: {
                    key: service_details[name].get(key)
                    for key in ("status", "endpoint")
                    if key in service_details[name]
                }
                for name in ("ovrtx", "ovphysx")
                if isinstance(service_details.get(name), Mapping)
            },
        }
        checks["installed_addon_import"] = True
    except Exception as exc:  # noqa: BLE001 - report exact installed add-on failure.
        checks["installed_addon_import"] = False
        diagnostics["installed_addon_error"] = f"{type(exc).__name__}: {exc}"
    return {
        "status": "pass" if all(checks.values()) else "blocked",
        "checks": checks,
        "diagnostics": diagnostics,
    }


def _prepare(settings: Mapping[str, Any]) -> dict[str, Any]:
    script = Path(settings["prepare_script"])
    if not script.is_file():
        return {"status": "not_required", "prepare_script": str(script)}
    completed = subprocess.run(
        [sys.executable, str(script)],
        text=True,
        capture_output=True,
        timeout=int(settings.get("prepare_timeout", 300)),
        check=False,
    )
    result = {
        "status": "pass" if completed.returncode == 0 else "fail",
        "returncode": completed.returncode,
        "prepare_script": str(script),
    }
    if completed.returncode != 0:
        result["stdout_tail"] = completed.stdout[-1200:]
        result["stderr_tail"] = completed.stderr[-1200:]
    return result


def _timeline_command(settings: Mapping[str, Any]) -> list[str]:
    command = [
        sys.executable,
        str(settings["timeline_runner"]),
        "--ov-repo",
        str(settings["ov_repo"]),
        "--runtime-root",
        str(settings["runtime_root"]),
        "--fixture",
        str(settings["fixture"]),
        "--output-dir",
        str(settings["output_dir"]),
        "--address",
        str(settings.get("address", "127.0.0.1:50095")),
        "--device",
        str(settings.get("device", "cpu")),
        "--steps",
        str(settings.get("steps", 240)),
        "--sample-every",
        str(settings.get("sample_every", 10)),
        "--fps",
        str(settings.get("fps", 60.0)),
    ]
    for prim_path in settings["body_prims"]:
        command.extend(["--body-prim", str(prim_path)])
    return command


def _simulate(settings: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = Path(settings["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        _timeline_command(settings),
        text=True,
        capture_output=True,
        timeout=int(settings.get("simulation_timeout", 300)),
        check=False,
    )
    status = _compact_file(output_dir / "status.json")
    status["returncode"] = completed.returncode
    if completed.returncode != 0:
        status["stdout_tail"] = completed.stdout[-1200:]
        status["stderr_tail"] = completed.stderr[-1200:]
    return status


def _close_scene_generation(settings: Mapping[str, Any]) -> str:
    import importlib

    addon = settings.get(
        "installed_addon_package",
        "bl_ext.user_default.ovrtx_blender_example.ovrtx_blender_example",
    )
    try:
        sessions = importlib.import_module(f"{addon}.scene_generation_sessions")
        sessions.close()
    except (ImportError, AttributeError) as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"
    return "closed"


def _restore_fixture_transforms(bpy: Any, scene: Any) -> bool:
    from mathutils import Matrix

    encoded = scene.get(FIXTURE_TRANSFORMS_KEY)
    if not isinstance(encoded, str):
        return False
    transforms = json.loads(encoded)
    scene_objects = {obj.name: obj for obj in scene.objects}
    restored = 0
    for name, values in transforms.items():
        obj = scene_objects.get(name)
        if obj is None or len(values) != 16:
            continue
        obj.matrix_world = Matrix([values[index : index + 4] for index in range(0, 16, 4)])
        restored += 1
    bpy.context.view_layer.update()
    return restored > 0


def _remember_fixture_transforms(scene: Any, objects: list[Any]) -> None:
    transforms = {
        obj.name: [float(value) for row in obj.matrix_world for value in row]
        for obj in objects
    }
    scene[FIXTURE_TRANSFORMS_KEY] = json.dumps(transforms, sort_keys=True)


def _switch_to_fixture_scene(bpy: Any, fixture: Path) -> Any:
    window = bpy.context.window
    if window is None:
        raise RuntimeError("a visible Blender window is required to replace the fixture scene")
    scene = bpy.data.scenes.new(f"NemoClaw OVPhysX - {fixture.stem}")
    window.scene = scene
    return scene


def _import_fixture(bpy: Any, fixture: Path, replace_scene: bool) -> list[Any]:
    source = str(fixture.resolve())
    scene = bpy.context.scene
    if replace_scene and scene.get(FIXTURE_SOURCE_KEY) == source:
        if not _restore_fixture_transforms(bpy, scene):
            raise RuntimeError("the active fixture scene has no reusable transform snapshot")
        return list(scene.objects)
    if replace_scene:
        # Keep the previous scene intact. Deleting all objects after OVRTX export and
        # USD import can crash Blender 5.1 in native object cleanup on repeated runs.
        scene = _switch_to_fixture_scene(bpy, fixture)
    before = set(bpy.data.objects)
    result = bpy.ops.wm.usd_import(filepath=str(fixture))
    if "FINISHED" not in result:
        raise RuntimeError(f"USD import failed: {result}")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        imported = list(bpy.context.scene.objects)
    if replace_scene:
        scene[FIXTURE_SOURCE_KEY] = source
        _remember_fixture_transforms(scene, imported)
    return imported


def _object_bounds(objects: list[Any]) -> tuple[Any, float]:
    from mathutils import Vector

    points = []
    for obj in objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return Vector((0.0, 0.0, 0.0)), 5.0
    minimum = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    maximum = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    return (minimum + maximum) * 0.5, max((maximum - minimum).length, 1.0)


def _ensure_camera_and_light(bpy: Any, objects: list[Any]) -> None:
    from mathutils import Vector

    center, extent = _object_bounds(objects)
    cameras = [obj for obj in objects if getattr(obj, "type", "") == "CAMERA"]
    camera = cameras[0] if cameras else None
    if camera is None:
        camera_data = bpy.data.cameras.new("NemoClawReplayCamera")
        camera = bpy.data.objects.new("NemoClawReplayCamera", camera_data)
        bpy.context.scene.collection.objects.link(camera)
        camera.location = center + Vector((extent * 0.65, -extent * 0.85, extent * 0.55))
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera

    if not any(getattr(obj, "type", "") == "LIGHT" for obj in objects):
        light_data = bpy.data.lights.new("NemoClawReplayKey", type="AREA")
        light_data.energy = 1800.0
        light_data.shape = "DISK"
        light_data.size = extent
        light = bpy.data.objects.new("NemoClawReplayKey", light_data)
        bpy.context.scene.collection.objects.link(light)
        light.location = center + Vector((extent * 0.3, -extent * 0.2, extent))
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()


def _configure_render(bpy: Any, settings: Mapping[str, Any]) -> None:
    scene = bpy.context.scene
    requested_engine = str(settings.get("render_engine", "BLENDER_WORKBENCH"))
    try:
        scene.render.engine = requested_engine
    except TypeError:
        fallback = "BLENDER_EEVEE" if requested_engine == "BLENDER_EEVEE_NEXT" else "BLENDER_WORKBENCH"
        scene.render.engine = fallback
    resolution = settings.get("resolution", [640, 360])
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    if scene.render.engine == "BLENDER_WORKBENCH":
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
    if scene.world is not None:
        scene.world.color = (0.04, 0.04, 0.04)


def _preview(settings: Mapping[str, Any]) -> dict[str, Any]:
    import bpy

    fixture = Path(settings["fixture"])
    output_dir = Path(settings["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_generation = _close_scene_generation(settings)
    imported = _import_fixture(bpy, fixture, bool(settings.get("replace_scene", True)))
    _ensure_camera_and_light(bpy, imported)
    _configure_render(bpy, settings)
    output = output_dir / "starting-scene.png"
    bpy.context.scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    return {
        "status": "pass",
        "source_usd": str(fixture),
        "object_count": len(imported),
        "render_engine": bpy.context.scene.render.engine,
        "preview": str(output),
        "scene_generation": scene_generation,
    }


def _name_candidates(prim_path: str) -> list[str]:
    leaf = prim_path.rstrip("/").split("/")[-1]
    return [prim_path, leaf, leaf.replace("-", "_"), leaf.replace("_", "-")]


def _resolve_body_objects(bpy: Any, prim_paths: list[str], explicit: Mapping[str, str]) -> dict[str, Any]:
    scene_objects = {obj.name: obj for obj in bpy.context.scene.objects}
    mapping = {}
    for prim_path in prim_paths:
        requested = explicit.get(prim_path)
        candidates = ([requested] if requested else []) + _name_candidates(prim_path)
        obj = next((scene_objects.get(name) for name in candidates if name and scene_objects.get(name)), None)
        if obj is None:
            leaf = prim_path.rstrip("/").split("/")[-1].lower()
            obj = next(
                (
                    item
                    for item in bpy.context.scene.objects
                    if item.name.lower() == leaf or item.name.lower().startswith(f"{leaf}.")
                ),
                None,
            )
        if obj is None:
            raise KeyError(f"no Blender object found for OVPhysX prim {prim_path}")
        mapping[prim_path] = obj
    return mapping


def _apply_states(mapping: Mapping[str, Any], states: list[Mapping[str, Any]]) -> None:
    from mathutils import Quaternion, Vector

    for state in states:
        obj = mapping.get(str(state.get("prim_path")))
        if obj is None:
            continue
        translate = state.get("translate", {})
        orient = state.get("orient", {})
        if translate.get("found", True):
            obj.location = Vector((float(translate["x"]), float(translate["y"]), float(translate["z"])))
        if orient.get("found", True):
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = Quaternion(
                (float(orient["r"]), float(orient["i"]), float(orient["j"]), float(orient["k"]))
            )


def _replay(settings: Mapping[str, Any]) -> dict[str, Any]:
    import bpy

    output_dir = Path(settings["output_dir"])
    timeline_path = Path(settings.get("timeline", output_dir / "pose-timeline.json"))
    timeline = _load_json(timeline_path)
    if timeline.get("physics_source") != "native-ovphysx-readback":
        raise ValueError("timeline is not labeled as native OVPhysX readback")

    scene_generation = _close_scene_generation(settings)
    imported = _import_fixture(
        bpy, Path(timeline["source_usd"]), bool(settings.get("replace_scene", True))
    )
    _ensure_camera_and_light(bpy, imported)
    _configure_render(bpy, settings)
    mapping = _resolve_body_objects(
        bpy, list(timeline["body_prims"]), settings.get("body_map", {})
    )

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.png"):
        stale.unlink()
    for index, sample in enumerate(timeline["samples"]):
        _apply_states(mapping, sample["states"])
        bpy.context.view_layer.update()
        bpy.context.scene.frame_set(index + 1)
        bpy.context.scene.render.filepath = str(frames_dir / f"{index:04d}.png")
        bpy.ops.render.render(write_still=True)

    gif_path = output_dir / str(settings.get("gif_name", "ovphysx-replay.gif"))
    ffmpeg = str(settings.get("ffmpeg", shutil.which("ffmpeg") or "/usr/bin/ffmpeg"))
    gif_fps = int(settings.get("gif_fps", 12))
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-framerate",
            str(gif_fps),
            "-i",
            str(frames_dir / "%04d.png"),
            "-vf",
            "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            str(gif_path),
        ],
        text=True,
        capture_output=True,
        timeout=int(settings.get("render_timeout", 900)),
        check=False,
    )
    result = {
        "status": "pass" if completed.returncode == 0 and gif_path.is_file() else "fail",
        "physics_source": "native-ovphysx-readback",
        "render_class": "blender-replay",
        "render_engine": bpy.context.scene.render.engine,
        "sample_count": len(timeline["samples"]),
        "scene_generation": scene_generation,
        "frames_dir": str(frames_dir),
        "gif": str(gif_path),
        "body_map": {prim: obj.name for prim, obj in mapping.items()},
        "ffmpeg_returncode": completed.returncode,
    }
    if completed.returncode != 0:
        result["ffmpeg_stderr_tail"] = completed.stderr[-1200:]
    _write_json(output_dir / "replay-status.json", result)
    return result


def _status(settings: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = Path(settings["output_dir"])
    return {
        "status": _compact_file(output_dir / "status.json"),
        "replay": _compact_file(output_dir / "replay-status.json"),
    }


def _run_configured_demo(settings: Mapping[str, Any]) -> dict[str, Any]:
    stages = (
        ("preflight", _preflight, {"pass"}),
        ("prepare", _prepare, {"pass", "not_required"}),
        ("preview", _preview, {"pass"}),
        ("simulate", _simulate, {"pass"}),
        ("replay", _replay, {"pass"}),
    )
    results: dict[str, dict[str, Any]] = {}
    for name, operation, accepted in stages:
        result = operation(settings)
        results[name] = result
        if result.get("status") not in accepted:
            return {
                "status": "blocked" if name == "preflight" else "fail",
                "failed_stage": name,
                "receipt": result,
            }

    simulation = results["simulate"]
    replay = results["replay"]
    return {
        "status": "pass",
        "native_status": simulation.get("native_status"),
        "physics_source": replay.get("physics_source"),
        "render_class": replay.get("render_class"),
        "sample_count": simulation.get("sample_count"),
        "gif": replay.get("gif"),
        "simulation_receipt": simulation.get("path"),
        "replay_receipt": str(Path(settings["output_dir"]) / "replay-status.json"),
    }


def dispatch(request: Mapping[str, Any]) -> dict[str, Any]:
    action = str(request.get("action", "status"))
    settings = _settings(request)
    actions = {
        "preflight": _preflight,
        "prepare": _prepare,
        "preview": _preview,
        "simulate": _simulate,
        "replay": _replay,
        "status": _status,
        "run_configured_demo": _run_configured_demo,
    }
    if action not in actions:
        raise ValueError(f"unknown action {action!r}; expected one of {sorted(actions)}")
    result = {"action": action, **actions[action](settings)}
    print(json.dumps(result, sort_keys=True, default=str))
    return result


if "OVPHYSX_REQUEST" in globals():
    OVPHYSX_RESULT = dispatch(globals()["OVPHYSX_REQUEST"])


if __name__ == "__main__":
    request = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"action": "status"}
    dispatch(request)
