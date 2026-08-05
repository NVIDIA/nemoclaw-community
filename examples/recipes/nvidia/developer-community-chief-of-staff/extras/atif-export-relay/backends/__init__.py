# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Storage-backend registry for atif-export-relay.

The relay picks a backend at startup from `ATIF_RELAY_DOWNSTREAM`. To add a
new backend (Azure Blob, GCS, custom non-S3 endpoint, etc.):

1. Create `backends/<name>.py` with `class <Name>Backend(StorageBackend)`
   implementing the ABC at [backends/base.py](base.py).
2. Add the backend's SDK to the relay's pip install in the Dockerfile.
3. Add `"<name>": <Name>Backend` to BACKENDS below.

The handler in `relay.py` is backend-agnostic — no changes needed there.
"""

from __future__ import annotations

import sys

from .base import (
    BackendError,
    BackendTransportError,
    PutResult,
    StorageBackend,
)
from .minio import MinioBackend
from .s3 import S3Backend
from .s3_compatible import S3CompatibleBackend
from .s3_endpoint import S3CompatibleEndpointBackend

__all__ = [
    "BACKENDS",
    "BackendError",
    "BackendTransportError",
    "PutResult",
    "S3CompatibleBackend",
    "S3CompatibleEndpointBackend",
    "StorageBackend",
    "build_backend",
]

BACKENDS: dict[str, type[StorageBackend]] = {
    "s3": S3Backend,            # AWS S3 — IMDS credential chain, no endpoint
    "minio": MinioBackend,      # local-dev preset (MINIO_* env, localhost:9000)
    "s3-compatible": S3CompatibleEndpointBackend,  # OCI / Nebius / GCS-XML / self-hosted
}


def build_backend(name: str) -> StorageBackend:
    cls = BACKENDS.get(name)
    if cls is None:
        sys.stderr.write(
            f"unsupported ATIF_RELAY_DOWNSTREAM: {name!r} "
            f"(available: {sorted(BACKENDS)})\n"
        )
        sys.exit(2)
    return cls.from_env()
