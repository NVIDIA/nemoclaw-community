# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Operator-only host helper for adding videos to the VSS sandbox.

This module intentionally registers no Hermes hooks or tools. Chat content is
untrusted and must never select a host path to read. The host-side ``swarm
video-add PATH`` command calls :func:`upload_video_from_operator` explicitly
after it has verified ownership of the target sandbox.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
MAX_BYTES = 40 * 1024 * 1024
DEST_DIR = "/sandbox/videos"


def register(_ctx):
    """Keep the host plugin inert; operator commands own host-file access."""
    logger.info("dropbox: automatic host-file handling is disabled")


def upload_video_from_operator(source: str | os.PathLike[str], sandbox: str) -> tuple[bool, str]:
    """Copy one explicitly selected host video into an owned VSS sandbox.

    Sandbox ownership is checked by the ``swarm`` command before this helper is
    called. This function uses an already-open file descriptor so a final-path
    symlink swap cannot change which host file is copied.
    """
    target = (sandbox or "").strip()
    if not target:
        return False, "the target sandbox is empty"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", target):
        return False, "the target sandbox name is invalid"

    try:
        path = Path(source).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return False, f"video path is invalid: {exc}"
    if path.suffix.lower() not in VIDEO_EXT:
        return False, f"video must use one of: {', '.join(sorted(VIDEO_EXT))}"
    try:
        if path.is_symlink():
            return False, "symbolic-link video paths are not accepted"
        before_open = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before_open.st_mode):
            return False, "video path is not a regular file"
    except (OSError, ValueError) as exc:
        return False, f"cannot inspect the video: {exc}"

    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except (OSError, ValueError) as exc:
        return False, f"cannot open the video: {exc}"

    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            return False, "video path is not a regular file"
        if (metadata.st_dev, metadata.st_ino) != (before_open.st_dev, before_open.st_ino):
            return False, "video path changed while it was being opened"
        if metadata.st_size == 0:
            return False, "video is empty"
        if metadata.st_size > MAX_BYTES:
            return False, (
                f"video is {metadata.st_size // (1024 * 1024)} MiB; "
                f"the limit is {MAX_BYTES // (1024 * 1024)} MiB"
            )
        if not shutil.which("openshell"):
            return False, "openshell is not on PATH"

        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
        if not safe_name or safe_name in {".", ".."}:
            return False, "video filename is not usable"
        if not safe_name[0].isalnum():
            safe_name = f"video_{safe_name}"

        try:
            stage = tempfile.mkdtemp(prefix="swarm-video.")
        except OSError as exc:
            return False, f"cannot create a private staging directory: {exc}"
        try:
            video_dir = Path(stage) / "videos"
            video_dir.mkdir()
            staged = video_dir / safe_name
            copied = 0
            with os.fdopen(fd, "rb", closefd=False) as source_file, staged.open("xb") as dest_file:
                while True:
                    chunk = source_file.read(min(1024 * 1024, MAX_BYTES + 1 - copied))
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > MAX_BYTES:
                        return False, f"video grew beyond the {MAX_BYTES // (1024 * 1024)} MiB limit while copying"
                    dest_file.write(chunk)
            if copied == 0:
                return False, "video became empty while copying"

            result = subprocess.run(
                [
                    "openshell",
                    "sandbox",
                    "upload",
                    "--no-git-ignore",
                    target,
                    str(video_dir),
                    "/sandbox",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "upload failed").strip()[:200]
                return False, detail
            return True, safe_name
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"video upload failed: {exc}"
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add one host video to the VSS sandbox")
    parser.add_argument("--sandbox", required=True, help=argparse.SUPPRESS)
    parser.add_argument("source", help="host path selected by the operator")
    args = parser.parse_args(argv)
    ok, detail = upload_video_from_operator(args.source, args.sandbox)
    if ok:
        # Machine-readable contract for `swarm video-add`; that wrapper owns
        # the user-facing status line.
        print(detail)
        return 0
    print(f"video-add failed: {detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
