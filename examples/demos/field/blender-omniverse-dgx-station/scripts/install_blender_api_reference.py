#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Extract a versioned Blender Python API archive inside the sandbox."""

import shutil
import sys
import zipfile
from pathlib import Path


if len(sys.argv) != 3:
    raise SystemExit("usage: install_blender_api_reference.py ARCHIVE DESTINATION")

archive = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
temporary = destination.with_name(f"{destination.name}.extracting")

if temporary.exists():
    shutil.rmtree(temporary)
temporary.mkdir(parents=True)

with zipfile.ZipFile(archive) as bundle:
    bundle.extractall(temporary)

indexes = list(temporary.rglob("index.html"))
if not indexes:
    raise RuntimeError(f"no index.html found in {archive}")

source_root = min(indexes, key=lambda path: len(path.parts)).parent
if destination.exists():
    shutil.rmtree(destination)
destination.parent.mkdir(parents=True, exist_ok=True)
if source_root == temporary:
    temporary.rename(destination)
else:
    shutil.move(str(source_root), destination)
    shutil.rmtree(temporary)

archive.unlink()
print(f"installed Blender Python API reference at {destination}")
