# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MinIO backend — local-dev preset of the generic S3-compatible endpoint backend.

MinIO is just an S3-compatible store at a fixed local endpoint, so this is a thin
preset of [s3_endpoint.py](s3_endpoint.py)'s `S3CompatibleEndpointBackend`. It
reads the SAME unified `ATIF_RELAY_S3_*` env as every other custom-endpoint store
— it only differs by supplying local-dev DEFAULTS (http://localhost:9000 +
minioadmin) so MinIO stays zero-config, where `s3-compatible` requires them
(fail-loud). External stores (OCI / Nebius / GCS) use `s3-compatible`.
"""

from __future__ import annotations

import os

from .prefixers import build_prefixer
from .s3_endpoint import S3CompatibleEndpointBackend


class MinioBackend(S3CompatibleEndpointBackend):
    label = "minio"

    @classmethod
    def from_env(cls) -> MinioBackend:
        # Same env names as the generic backend, but with local-dev defaults
        # instead of fail-loud — MinIO is zero-config out of the box.
        return cls(
            endpoint=os.environ.get("ATIF_RELAY_S3_ENDPOINT") or "http://localhost:9000",
            access_key=os.environ.get("ATIF_RELAY_S3_ACCESS_KEY") or "minioadmin",
            secret_key=os.environ.get("ATIF_RELAY_S3_SECRET_KEY") or "minioadmin",
            prefixer=build_prefixer(os.environ.get("ATIF_RELAY_PREFIXER", "none")),
            static_prefix=os.environ.get("ATIF_RELAY_KEY_PREFIX", ""),
            region=os.environ.get("ATIF_RELAY_S3_REGION") or "us-west-2",
        )
