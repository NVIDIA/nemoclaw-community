#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build or verify the portable Ask NemoClaw Chrome extension archive."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_TEMPLATE = ROOT / "extension" / "manifest.template.json"
ARCHIVE_ROOT = "ask-nemoclaw-extension"
RELEASE_DIR = ROOT / "release"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def extension_version() -> str:
    manifest = json.loads(MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    return manifest["version"]


def create_archive(output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ask-nemoclaw-release-") as temp_dir:
        extension_dir = Path(temp_dir) / ARCHIVE_ROOT
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "configure-extension.py"),
                "--output",
                str(extension_dir),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )

        manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("host_permissions") != []:
            raise SystemExit("portable release must not contain a deployment host permission")
        config = (extension_dir / "config.js").read_text(encoding="utf-8")
        if 'hermesOrigin: ""' not in config:
            raise SystemExit("portable release must not contain a deployment URL")

        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for source in sorted(extension_dir.iterdir(), key=lambda item: item.name):
                if not source.is_file():
                    continue
                member = ZipInfo(f"{ARCHIVE_ROOT}/{source.name}", FIXED_TIMESTAMP)
                member.compress_type = ZIP_DEFLATED
                member.external_attr = 0o100644 << 16
                archive.writestr(member, source.read_bytes(), compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the committed archive matches the extension source",
    )
    args = parser.parse_args()

    release = RELEASE_DIR / f"ask-nemoclaw-extension-{extension_version()}.zip"
    if not args.check:
        create_archive(release)
        print(f"Built portable extension release: {release}")
        return 0

    if not release.is_file():
        raise SystemExit(f"missing extension release artifact: {release}")
    with tempfile.TemporaryDirectory(prefix="ask-nemoclaw-release-check-") as temp_dir:
        expected = Path(temp_dir) / release.name
        create_archive(expected)
        if release.read_bytes() != expected.read_bytes():
            raise SystemExit(
                "extension release artifact is stale; run "
                "python3 scripts/build-extension-release.py"
            )
    print(f"Extension release artifact is current: {release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
