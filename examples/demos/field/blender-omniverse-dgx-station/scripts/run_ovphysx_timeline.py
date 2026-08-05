#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run native OVPhysX and retain authoritative body poses at fixed intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Mapping, Sequence


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ov-repo", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--body-prim", action="append", dest="body_prims", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--address", default="127.0.0.1:50095")
    parser.add_argument("--device", choices=("cpu", "gpu", "auto"), default="cpu")
    parser.add_argument("--steps", type=int, default=240)
    parser.add_argument("--sample-every", type=int, default=10)
    parser.add_argument("--fps", type=float, default=60.0)
    args = parser.parse_args(list(argv))
    if args.steps <= 0 or args.sample_every <= 0 or args.fps <= 0:
        parser.error("--steps, --sample-every, and --fps must be positive")
    return args


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_hash(states: Sequence[Mapping[str, Any]]) -> str:
    normalized = []
    for state in sorted(states, key=lambda item: str(item.get("prim_path", ""))):
        normalized.append(
            {
                key: state.get(key)
                for key in ("prim_path", "translate", "orient", "linear_velocity", "angular_velocity")
            }
        )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite(value: Any) -> bool:
    if isinstance(value, Mapping):
        return all(_finite(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_finite(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def _resolve_ovphysx_server(runtime_root: Path) -> Path:
    candidates = (
        runtime_root / "bin" / "ovphysx-bridge-server",
        runtime_root / "bin" / "ovphysx_grpc_server",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def _compact_status(output_dir: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": report["status"],
        "native_status": report.get("native_status"),
        "sample_count": report.get("poses", {}).get("samples", 0),
        "body_count": report.get("bodies", {}).get("discovered", 0),
        "timeline": str(output_dir / "pose-timeline.json"),
        "report": str(output_dir / "ovphysx-report.json"),
        "error": report.get("error"),
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    addon_root = args.ov_repo / "addon"
    server = _resolve_ovphysx_server(args.runtime_root)
    native = args.runtime_root / "native"
    ovphysx_root = args.runtime_root / "runtime" / "ovphysx"
    ovruntime_root = args.runtime_root / "runtime" / "ovruntime"
    required = [addon_root, args.fixture, server, native, ovphysx_root, ovruntime_root]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing required host paths: " + ", ".join(missing))

    sys.path.insert(0, str(addon_root))
    os.environ["OVPHYSX_ROOT"] = str(ovphysx_root)
    os.environ["OVRUNTIME_ROOT"] = str(ovruntime_root)

    from ovrtx_blender_example import bundled_runtime  # type: ignore[import-not-found]
    from ovrtx_blender_example.ovphysx_runtime_client import (  # type: ignore[import-not-found]
        DEFAULT_OVPHYSX_NATIVE_CLIENT_MODULE,
        OvphysxRuntimeClient,
    )
    from ovrtx_blender_example.shared_stage_config import (  # type: ignore[import-not-found]
        InteractiveSharedStageConfig,
    )

    worker_log = args.output_dir / "ovphysx-worker.log"
    timestep_ns = int(1_000_000_000 / args.fps)
    worker_command = bundled_runtime.serialize_command(
        [str(server), "--listen", args.address, "--device", args.device]
    )
    config = InteractiveSharedStageConfig(
        enabled=True,
        input_usd_path=str(args.fixture),
        server=str(server),
        ovphysx_address=args.address,
        ovphysx_worker_command=worker_command,
        device=args.device,
        body_root=str(Path(args.body_prims[0]).parent).replace("\\", "/"),
        body_prims=tuple(args.body_prims),
        physics_fps=args.fps,
        update_fps=args.fps,
        max_steps=args.steps,
        body_scale=1.0,
        worker_log_path=str(worker_log),
        ovphysx_native_client_module=DEFAULT_OVPHYSX_NATIVE_CLIENT_MODULE,
        ovphysx_native_client_path=str(native),
    )

    simulation_id = f"nemoclaw-timeline-{int(time.time())}"
    client = OvphysxRuntimeClient(config, simulation_id)
    samples: list[dict[str, Any]] = []
    created = False
    try:
        client.start()
        create_diagnostics = client.create_simulation()
        created = True
        states, initial_diagnostics = client.read_body_states(0)
        samples.append(
            {
                "step": 0,
                "simulation_time_ns": 0,
                "state_hash": _state_hash(states),
                "states": states,
            }
        )
        current_step = 0
        sample_diagnostics = []
        while current_step < args.steps:
            step_count = min(args.sample_every, args.steps - current_step)
            states, diagnostics = client.advance_and_read_body_states(
                current_step, step_count, timestep_ns
            )
            current_step += step_count
            samples.append(
                {
                    "step": current_step,
                    "simulation_time_ns": current_step * timestep_ns,
                    "state_hash": _state_hash(states),
                    "states": states,
                }
            )
            sample_diagnostics.append(
                {
                    "step": current_step,
                    "body_count": diagnostics.get("body_count"),
                    "total_ms": diagnostics.get("total_ms"),
                }
            )
    finally:
        shutdown_status = client.shutdown()

    discovered = sorted(
        {str(state.get("prim_path")) for sample in samples for state in sample["states"]}
    )
    timeline = {
        "schema_version": 1,
        "physics_source": "native-ovphysx-readback",
        "source_usd": str(args.fixture),
        "source_sha256": _sha256(args.fixture),
        "settings": {
            "fps": args.fps,
            "steps": args.steps,
            "sample_every": args.sample_every,
            "timestep_ns": timestep_ns,
            "device": args.device,
        },
        "body_prims": args.body_prims,
        "samples": samples,
    }
    _write_json(args.output_dir / "pose-timeline.json", timeline)

    finite = all(_finite(sample["states"]) for sample in samples)
    identity_ok = discovered == sorted(args.body_prims)
    report = {
        "status": "pass" if finite and identity_ok else "fail",
        "native_status": "pass-real",
        "source": {"path": str(args.fixture), "sha256": timeline["source_sha256"]},
        "runtime": {
            "server": str(server),
            "native_client": str(native),
            "device": args.device,
            "platform": platform.platform(),
        },
        "settings": timeline["settings"],
        "bodies": {
            "expected": len(args.body_prims),
            "discovered": len(discovered),
            "identity_check": "pass" if identity_ok else "fail",
            "prim_paths": discovered,
        },
        "poses": {
            "samples": len(samples),
            "finite": "pass" if finite else "fail",
            "initial_state_hash": samples[0]["state_hash"],
            "final_state_hash": samples[-1]["state_hash"],
        },
        "runtime_diagnostics": {
            "create": create_diagnostics,
            "initial_read": {
                "body_count": initial_diagnostics.get("body_count"),
                "read_ms": initial_diagnostics.get("read_ms"),
            },
            "samples": sample_diagnostics,
            "shutdown": shutdown_status,
            "simulation_created": created,
        },
        "artifacts": [
            str(args.output_dir / "pose-timeline.json"),
            str(args.output_dir / "ovphysx-report.json"),
            str(worker_log),
        ],
        "limitations": [
            "Contact and settling acceptance depend on the selected scene and are not inferred by this generic runner."
        ],
    }
    _write_json(args.output_dir / "ovphysx-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    status_path = args.output_dir / "status.json"
    _write_json(status_path, {"status": "running", "started_at_ns": time.time_ns()})
    try:
        report = _run(args)
    except Exception as exc:  # noqa: BLE001 - preserve the native failure for evidence.
        report = {
            "status": "blocked" if isinstance(exc, (FileNotFoundError, ImportError)) else "fail",
            "native_status": "blocked-preflight" if isinstance(exc, (FileNotFoundError, ImportError)) else "failed-real",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": [str(status_path)],
        }
        _write_json(args.output_dir / "ovphysx-report.json", report)
    compact = _compact_status(args.output_dir, report)
    _write_json(status_path, compact)
    print(json.dumps(compact, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
