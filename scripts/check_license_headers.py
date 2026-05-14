#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check SPDX license headers on repository source files."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

COPYRIGHT_TEXT = (
    "Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved."
)
LICENSE_ID = "Apache-2.0"
SPDX_MARKER = "SPDX-License-Identifier"

COMMENT_STYLES: dict[str, str] = {
    ".js": "//",
    ".py": "#",
    ".sh": "#",
    ".ts": "//",
    ".yaml": "#",
    ".yml": "#",
    ".toml": "#",
}

EXCLUDE_DIRS: set[str] = {
    ".git",
    ".planning",
    ".venv",
    "__pycache__",
}

EXCLUDE_FILES: set[str] = {
    ".gitkeep",
}


def is_dockerfile(path: Path) -> bool:
    return path.name == "Dockerfile" or path.name.startswith("Dockerfile.")


def get_comment_style(path: Path) -> str | None:
    if is_dockerfile(path):
        return "#"
    return COMMENT_STYLES.get(path.suffix)


def find_repo_root() -> Path:
    path = Path.cwd()
    while path != path.parent:
        if (path / ".git").exists():
            return path
        path = path.parent
    return Path.cwd()


def is_excluded(rel: Path) -> bool:
    if rel.name in EXCLUDE_FILES:
        return True
    rel_str = str(rel)
    return any(rel_str == dirname or rel_str.startswith(dirname + "/") for dirname in EXCLUDE_DIRS)


def discover_files(root: Path) -> list[Path]:
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if not is_excluded(rel_dir / d)]
        for filename in filenames:
            path = Path(dirpath) / filename
            rel = path.relative_to(root)
            if not is_excluded(rel) and get_comment_style(rel) is not None:
                results.append(path)
    return sorted(results)


def has_header(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return True
    return any(SPDX_MARKER in line for line in lines[:10])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if any source file is missing an SPDX header.")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional file paths to check.")
    args = parser.parse_args()

    root = find_repo_root()
    if args.paths:
        files = [
            path.resolve()
            for path in args.paths
            if path.is_file()
            and not is_excluded(path.resolve().relative_to(root))
            and get_comment_style(path.resolve().relative_to(root)) is not None
        ]
    else:
        files = discover_files(root)

    missing = [path.relative_to(root) for path in files if not has_header(path)]
    if missing:
        for path in missing:
            print(f"  MISSING: {path}")
        print(f"\n{len(missing)} file(s) missing SPDX headers.")
        return 1

    print(f"All {len(files)} checked source files have SPDX headers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
