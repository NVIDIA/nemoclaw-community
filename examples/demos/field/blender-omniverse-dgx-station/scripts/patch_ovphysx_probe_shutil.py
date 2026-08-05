#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add the missing shutil import to the current OVPhysX probe."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()

    path = args.repo.expanduser().resolve() / "scripts" / "run_ovphysx_drop_probe.py"
    source = path.read_text(encoding="utf-8")
    if "import shutil\n" in source:
        print(f"already patched: {path}")
        return 0

    marker = "import platform\nimport statistics\n"
    if marker not in source:
        raise SystemExit(f"unsupported probe source; import marker not found: {path}")

    path.write_text(
        source.replace(marker, "import platform\nimport shutil\nimport statistics\n", 1),
        encoding="utf-8",
    )
    print(f"patched missing shutil import: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
