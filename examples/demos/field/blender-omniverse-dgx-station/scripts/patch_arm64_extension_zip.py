#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patch an OVRTX extension ZIP so Blender Linux ARM64 accepts it.

This is a temporary workaround for development artifacts that declare
linux-aarch64 in filenames/runtime payloads but omit Blender's linux-arm64
extension platform token in blender_manifest.toml.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_zip", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()

    if args.input_zip.resolve() == args.output_zip.resolve():
        parser.error("output_zip must be different from input_zip")

    found_manifest = False
    patched = False

    with zipfile.ZipFile(args.input_zip, "r") as src, zipfile.ZipFile(
        args.output_zip, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith("blender_manifest.toml"):
                found_manifest = True
                text = data.decode("utf-8")
                if "linux-arm64" not in text:
                    text, count = re.subn(
                        r'platforms\s*=\s*\[([^\]]*)\]',
                        lambda match: _add_platform(match.group(1)),
                        text,
                        count=1,
                    )
                    patched = bool(count)
                data = text.encode("utf-8")
            dst.writestr(info, data)

    if not found_manifest:
        raise SystemExit("blender_manifest.toml not found in extension ZIP")
    if patched:
        print(f"patched {args.output_zip}")
    else:
        print(f"copied {args.output_zip}; linux-arm64 already present")
    return 0


def _add_platform(inner: str) -> str:
    values = [item.strip() for item in inner.split(",") if item.strip()]
    values.append('"linux-arm64"')
    return "platforms = [" + ", ".join(values) + "]"


if __name__ == "__main__":
    raise SystemExit(main())
