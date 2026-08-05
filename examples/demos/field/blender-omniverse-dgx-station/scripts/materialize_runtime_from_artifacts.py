#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install a paired OVRTX/OVPhysX release from local verified artifacts.

The runtime implementation is imported from the selected add-on ZIP so a
mutable source checkout cannot drift from the release being installed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--addon-zip", type=Path, required=True, help="ov-blender-example extension ZIP")
    parser.add_argument("--artifact-dir", type=Path, required=True, help="directory containing runtime component archives")
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path.home()
        / ".config/blender/5.1/extensions/.user/user_default/ovrtx_blender_example",
        help="Blender extension storage root",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(args.addon_zip, "r") as archive:
            archive.extractall(tmp_path)
        extension_root = _find_extension_root(tmp_path)
        sys.path.insert(0, str(extension_root))

        from ovrtx_blender_example.runtime_manifest import (  # noqa: PLC0415
            RUNTIME_MANIFEST_NAME,
            load_manifest_pin,
            parse_manifest_bytes,
        )
        from ovrtx_blender_example.runtime_materializer import (  # noqa: PLC0415
            materialize_runtime,
        )
        from ovrtx_blender_example.runtime_store import verify  # noqa: PLC0415

        expected_manifest_sha256 = load_manifest_pin(extension_root)
        manifest_path = args.artifact_dir / RUNTIME_MANIFEST_NAME
        if not manifest_path.is_file():
            raise SystemExit(f"missing release manifest: {manifest_path}")
        manifest = parse_manifest_bytes(manifest_path.read_bytes())
        if manifest.sha256 != expected_manifest_sha256:
            raise SystemExit(
                "The release manifest does not match the manifest pinned by the add-on ZIP."
            )

        if args.storage_root.exists():
            stale = args.storage_root / "runtimes" / manifest.platform
            shutil.rmtree(stale, ignore_errors=True)

        current = materialize_runtime(
            expected_manifest_sha256,
            args.storage_root,
            source=str(args.artifact_dir.resolve()),
        )
        status = verify(args.storage_root, manifest)
        print(f"installed: {current}")
        print(f"state: {status.state}")
        print(f"message: {status.message}")
        if status.state != "ready":
            return 1
    return 0


def _find_extension_root(root: Path) -> Path:
    pins = [path for path in root.rglob("runtime-bundle-manifest.sha256") if path.is_file()]
    if not pins:
        raise SystemExit("runtime-bundle-manifest.sha256 not found in add-on ZIP")
    extension_root = pins[0].parent
    if not (extension_root / "ovrtx_blender_example").is_dir():
        raise SystemExit(
            "runtime manifest was found, but ovrtx_blender_example package is missing"
        )
    return extension_root


if __name__ == "__main__":
    raise SystemExit(main())
