# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Select the files that setup copies from the approved folder into the sandbox.

This filter runs on the host before the copy. It is not the sandbox boundary.
It keeps a symbolic link, a special file, or an oversized file in the approved
folder from carrying other host content into the sandbox. A file can still
change between this check and the copy, so run setup only on a folder that
untrusted processes cannot write to.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_MAX_FILE_BYTES = 1024 * 1024
DEFAULT_MAX_FILES = 200


class WorkspaceRejected(PermissionError):
    """The approved folder contains an entry that setup must not copy."""


@dataclass(frozen=True)
class ApprovedFile:
    source: Path
    relative: PurePosixPath
    size: int


def _resolved_root(root: Path) -> Path:
    if os.path.islink(root):
        raise WorkspaceRejected("approved folder must not be a symbolic link")
    resolved = Path(root).resolve(strict=True)
    if not resolved.is_dir():
        raise WorkspaceRejected("approved folder is not a directory")
    return resolved


def resolve_approved_path(root: Path, requested: str) -> Path:
    """Return the path of one regular file inside the approved folder.

    Reject an absolute path, a parent reference, and any symbolic link on the
    way to the file.
    """
    base = _resolved_root(root)
    candidate = PurePosixPath(requested.replace(os.sep, "/"))
    if not requested or candidate.is_absolute() or Path(requested).is_absolute():
        raise WorkspaceRejected("path must be relative to the approved folder")
    if ".." in candidate.parts:
        raise WorkspaceRejected("path must not contain a parent reference")

    current = base
    for part in candidate.parts:
        current = current / part
        if os.path.islink(current):
            raise WorkspaceRejected("path must not pass through a symbolic link")
    try:
        info = os.lstat(current)
    except OSError as exc:
        raise WorkspaceRejected("path does not exist in the approved folder") from exc
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceRejected("path is not a regular file")
    if base not in current.resolve(strict=True).parents:
        raise WorkspaceRejected("path leaves the approved folder")
    return current


def list_approved_files(
    root: Path,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> list[ApprovedFile]:
    """Return every file to copy, or raise on the first entry that is not accepted."""
    base = _resolved_root(root)
    approved: list[ApprovedFile] = []
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(directory) / name
            relative = PurePosixPath(path.relative_to(base).as_posix())
            if any(ord(char) < 32 for char in name) or ":" in name:
                raise WorkspaceRejected("name has a character that setup does not copy")
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                raise WorkspaceRejected("symbolic link in approved folder: %s" % relative)
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceRejected("special file in approved folder: %s" % relative)
            if info.st_size > max_file_bytes:
                raise WorkspaceRejected("file is larger than the limit: %s" % relative)
            approved.append(ApprovedFile(source=path, relative=relative, size=info.st_size))
            if len(approved) > max_files:
                raise WorkspaceRejected("approved folder has more files than the limit")
    return approved
