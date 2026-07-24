#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Download and verify one explicit ov-blender-example GitHub Release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


RELEASE_URL_PATTERN = re.compile(
    r"^/NVIDIA-Omniverse/omniverse-labs/releases/tag/([^/]+)$"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-url",
        required=True,
        help="Exact github.com Release page URL paired with the add-on ZIP",
    )
    parser.add_argument(
        "--platform",
        default="linux-aarch64",
        help="Expected release platform (default: linux-aarch64)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    tag = _release_tag(args.release_url)
    expected_tag = f"ov-blender-example-{args.platform}"
    if tag != expected_tag:
        raise SystemExit(
            f"release tag {tag!r} does not match expected platform tag {expected_tag!r}"
        )

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    download_root = (
        "https://github.com/NVIDIA-Omniverse/omniverse-labs/releases/download/"
        f"{quote(tag, safe='')}/"
    )

    addon_name = f"ov-blender-example-{args.platform}.zip"
    manifest_name = "runtime-bundle-manifest.json"
    _download(download_root + quote(addon_name, safe=""), output_dir / addon_name)
    _download(
        download_root + quote(manifest_name, safe=""),
        output_dir / manifest_name,
    )

    components = _manifest_components(output_dir / manifest_name, args.platform)
    for component in components:
        target = output_dir / component["filename"]
        if _matches(target, component["size_bytes"], component["sha256"]):
            print(f"verified existing: {target.name}")
            continue
        _download(
            download_root + quote(component["filename"], safe=""),
            target,
            expected_size=component["size_bytes"],
            expected_sha256=component["sha256"],
        )

    print(f"release: {args.release_url}")
    print(f"artifacts: {output_dir}")
    print(f"components: {len(components)}")
    return 0


def _release_tag(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise SystemExit("release URL must use https://github.com")
    match = RELEASE_URL_PATTERN.fullmatch(parsed.path.rstrip("/"))
    if match is None or parsed.params or parsed.query or parsed.fragment:
        raise SystemExit(
            "release URL must be an exact NVIDIA-Omniverse/omniverse-labs Release page"
        )
    return match.group(1)


def _manifest_components(path: Path, expected_platform: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid runtime manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("platform") != expected_platform:
        raise SystemExit(
            f"runtime manifest platform does not match {expected_platform!r}"
        )
    raw_components = payload.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise SystemExit("runtime manifest has no components")

    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_components:
        if not isinstance(raw, dict):
            raise SystemExit("runtime manifest component is not an object")
        filename = raw.get("filename")
        sha256 = raw.get("sha256")
        size_bytes = raw.get("size_bytes")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or "\\" in filename
            or filename in seen
        ):
            raise SystemExit(f"invalid runtime component filename: {filename!r}")
        if (
            not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise SystemExit(f"invalid SHA-256 for runtime component {filename}")
        if not isinstance(size_bytes, int) or size_bytes <= 0:
            raise SystemExit(f"invalid size for runtime component {filename}")
        seen.add(filename)
        components.append(
            {"filename": filename, "sha256": sha256, "size_bytes": size_bytes}
        )
    return components


def _download(
    url: str,
    target: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading: {target.name}")
    request = Request(url, headers={"User-Agent": "nemoclaw-community-blender-example"})
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        digest = hashlib.sha256()
        size = 0
        try:
            with urlopen(request, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    temporary.write(block)
                    digest.update(block)
                    size += len(block)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    actual_sha256 = digest.hexdigest()
    if expected_size is not None and size != expected_size:
        temporary_path.unlink(missing_ok=True)
        raise SystemExit(
            f"size mismatch for {target.name}: expected {expected_size}, got {size}"
        )
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise SystemExit(
            f"SHA-256 mismatch for {target.name}: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )
    shutil.move(temporary_path, target)
    print(f"downloaded: {target.name} ({size} bytes, sha256={actual_sha256})")


def _matches(path: Path, expected_size: int, expected_sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size != expected_size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == expected_sha256


if __name__ == "__main__":
    raise SystemExit(main())
