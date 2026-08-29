# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Export the self-test SVG to the raster the README shows, recording its source.

The catalog allows only raster formats in a README, so the image a reader sees
cannot be the SVG the suite checks. This writes the SVG's SHA-256 into a PNG
`tEXt` chunk, which travels with the file and lets a test prove the two describe
the same run without needing OCR or file timestamps -- git preserves neither.

The stamp is attached only to freshly rendered bytes. There is no way to stamp
an existing file: that would let a digest vouch for pixels nobody re-rendered.

Usage:
    python3 tools/export_selftest_image.py
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


def _without_stamp(data: bytes) -> bytes:
    """Drop any existing source stamp, so stamping replaces rather than appends."""
    out, offset = bytearray(data[:8]), 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if not (kind == b"tEXt" and body.startswith(KEYWORD + b"\0")):
            out += data[offset:offset + 12 + length]
        offset += 12 + length
    return bytes(out)


def _stamped(rendered: bytes, digest: str) -> bytes:
    """Attach a source digest to bytes that were just rendered.

    Deliberately takes the image as an argument rather than a path. A
    stamp-in-place entry point let a digest be attached to pixels that were
    never re-rendered: change the SVG, strip the old chunk, stamp, and a digest
    check passes over stale content. The only caller is the render below.
    """
    data = _without_stamp(rendered)
    end = data.rindex(b"\x00\x00\x00\x00IEND")
    body = KEYWORD + b"\0" + digest.encode("ascii")
    return data[:end] + _chunk(b"tEXt", body) + data[end:]


def export() -> None:
    """Render the SVG and stamp the result. There is no stamp-only path."""
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["qlmanage", "-t", "-s", "1218", "-o", work, str(SVG)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        rendered = next(Path(work).glob("*.png")).read_bytes()
    PNG.write_bytes(_stamped(rendered, source_digest()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    export()
    print(f"{PNG.relative_to(REPO)} records source-sha256 {read_stamp()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
