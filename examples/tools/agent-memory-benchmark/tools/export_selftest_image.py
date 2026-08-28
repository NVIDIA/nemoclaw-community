# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Export the self-test SVG to the raster the README shows, recording its source.

The catalog allows only raster formats in a README, so the image a reader sees
cannot be the SVG the suite checks. This writes the SVG's SHA-256 into a PNG
`tEXt` chunk, which travels with the file and lets a test prove the two describe
the same run without needing OCR or file timestamps -- git preserves neither.

Usage:
    python3 tools/export_selftest_image.py            # re-export and stamp
    python3 tools/export_selftest_image.py --stamp    # stamp an existing PNG
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SVG = REPO / "docs" / "assets" / "offline-self-test.svg"
PNG = REPO / "docs" / "assets" / "offline-self-test.png"
KEYWORD = b"source-sha256"


def source_digest(svg: Path = SVG) -> str:
    return hashlib.sha256(svg.read_bytes()).hexdigest()


def read_stamp(png: Path = PNG) -> str | None:
    """The SHA-256 the PNG records for the SVG it was exported from."""
    data = png.read_bytes()
    offset = 8  # PNG signature
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if kind == b"tEXt" and body.startswith(KEYWORD + b"\0"):
            return body[len(KEYWORD) + 1:].decode("ascii")
        offset += 12 + length
    return None


def _chunk(kind: bytes, body: bytes) -> bytes:
    import zlib
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def stamp(png: Path = PNG, digest: str | None = None) -> None:
    digest = digest or source_digest()
    data = png.read_bytes()
    end = data.rindex(b"\x00\x00\x00\x00IEND")
    body = KEYWORD + b"\0" + digest.encode("ascii")
    png.write_bytes(data[:end] + _chunk(b"tEXt", body) + data[end:])


def export() -> None:
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["qlmanage", "-t", "-s", "1218", "-o", work, str(SVG)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        rendered = next(Path(work).glob("*.png"))
        PNG.write_bytes(rendered.read_bytes())
    stamp()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", action="store_true",
                        help="record the source digest on the existing PNG")
    args = parser.parse_args()
    if args.stamp:
        stamp()
    else:
        export()
    print(f"{PNG.relative_to(REPO)} records source-sha256 {read_stamp()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
