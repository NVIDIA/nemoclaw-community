#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fetch and verify pinned third-party assets used by the static catalog."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


MERMAID_VERSION = "11.17.2"
MERMAID_URL = (
    "https://cdn.jsdelivr.net/npm/@mermaid-js/tiny@"
    f"{MERMAID_VERSION}/dist/mermaid.tiny.js"
)
MERMAID_SHA256 = (
    "7a644017d37f93c8359790884e6b67fb1f747c78eb20475952404bd87190a3f8"
)
MERMAID_CACHE_PATH = Path(".cache/catalog/mermaid.tiny.js")
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_cached_asset(root: Path) -> Path:
    target = root / MERMAID_CACHE_PATH
    if (
        not target.is_file()
        or target.is_symlink()
        or not target.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError(
            "The pinned Mermaid browser asset is missing. Run "
            "`python3 scripts/fetch_catalog_assets.py`."
        )
    actual_hash = sha256_file(target)
    if actual_hash != MERMAID_SHA256:
        raise ValueError(
            "The cached Mermaid browser asset failed its SHA-256 check. "
            "Run `python3 scripts/fetch_catalog_assets.py` to replace it."
        )
    return target


def fetch_asset(root: Path) -> Path:
    target = root / MERMAID_CACHE_PATH
    if not target.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError("Refusing to use a cache directory outside the repository.")
    if target.is_file() and not target.is_symlink():
        if sha256_file(target) == MERMAID_SHA256:
            return target
    if target.is_symlink():
        raise ValueError(f"Refusing to replace symlinked cache asset: {target}")

    request = Request(
        MERMAID_URL,
        headers={"User-Agent": "nemoclaw-community-catalog-builder/1"},
    )
    try:
        with urlopen(request, timeout=45) as response:  # noqa: S310 - pinned hash.
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > MAX_DOWNLOAD_BYTES:
                raise ValueError("The Mermaid download exceeds the 4 MiB limit.")
            content = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (OSError, URLError) as error:
        raise ValueError(f"Unable to download the pinned Mermaid asset: {error}") from error

    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The Mermaid download exceeds the 4 MiB limit.")
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != MERMAID_SHA256:
        raise ValueError(
            "Downloaded Mermaid asset failed its SHA-256 check; refusing to cache it."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".mermaid-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def find_repo_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the cached asset without downloading it.",
    )
    args = parser.parse_args(argv)
    root = find_repo_root()
    try:
        target = validate_cached_asset(root) if args.check else fetch_asset(root)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Mermaid {MERMAID_VERSION} asset ready: {target.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
