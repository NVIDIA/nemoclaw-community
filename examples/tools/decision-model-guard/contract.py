# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Load the pinned, locally generated OpenShell middleware contract."""

import sys
from pathlib import Path

BINDINGS = Path(__file__).resolve().parent / ".cache/bindings"
if not (BINDINGS / "supervisor_middleware_pb2.py").exists():
    raise RuntimeError("Run `uv run setup_bindings.py` before starting the example.")
sys.path.insert(0, str(BINDINGS))

import extension_pb2 as extension  # noqa: E402
import supervisor_middleware_pb2 as pb  # noqa: E402
import supervisor_middleware_pb2_grpc as rpc  # noqa: E402

__all__ = ["extension", "pb", "rpc"]
