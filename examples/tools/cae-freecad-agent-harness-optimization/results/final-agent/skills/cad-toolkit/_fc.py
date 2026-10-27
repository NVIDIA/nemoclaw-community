# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Make FreeCAD importable from plain python3 (the conda lib dir beside freecadcmd)."""
import os
import shutil
import sys


def load():
    try:
        import FreeCAD  # noqa: F401
        return
    except ImportError:
        pass
    exe = shutil.which('freecadcmd') or '/opt/conda/bin/freecadcmd'
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(exe))), 'lib')
    for p in (lib, '/opt/conda/lib'):
        if p not in sys.path:
            sys.path.append(p)
    import FreeCAD  # noqa: F401


load()
