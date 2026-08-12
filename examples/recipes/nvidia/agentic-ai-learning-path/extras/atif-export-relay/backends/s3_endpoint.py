# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generic S3-compatible backend for a custom endpoint + static credentials.

Covers any S3-compatible object store reached via an explicit `endpoint_url` and
access/secret keys: MinIO (local dev, via the thin `MinioBackend` preset), and
external stores like OCI Object Storage (S3 Compatibility API), Nebius, GCS
XML/interop, or self-hosted. AWS S3 proper uses [s3.py](s3.py) instead (the IMDS
credential chain, no endpoint).

All the PutObject / key-prefix / logging machinery is inherited from
[s3_compatible.py](s3_compatible.py); only the boto3 client construction
(explicit endpoint, static creds, path-style addressing) and the startup probe
differ. Config comes from the relay-owned `ATIF_RELAY_S3_*` env vars.

Adding a new external S3-compatible cloud is therefore just config — set
`ATIF_RELAY_BACKEND=s3-compatible` plus the endpoint/keys; no new code. (A
non-S3 store such as Azure Blob would instead implement the generic
`StorageBackend` ABC directly with its own SDK.)
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

import boto3
from botocore.client import Config

from .prefixers import build_prefixer
from .s3_compatible import S3CompatibleBackend

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _required(name: str, who: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"required env var unset: {name} ({who})\n")
        sys.exit(2)
    return v


def _validate_endpoint(endpoint: str) -> None:
    """Refuse a remote cleartext endpoint — real creds + trace bodies would go
    over the wire unencrypted. `https://` is always fine; `http://` is allowed
    only for loopback (local MinIO). Mirrors the https-required check that
    scripts/_lib.sh enforces on ATIF_RELAY_ENDPOINT.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and (parsed.hostname or "") in _LOOPBACK_HOSTS:
        return
    sys.stderr.write(
        f"ATIF_RELAY_S3_ENDPOINT must be https:// for a remote store "
        f"(http:// is allowed only for loopback / local MinIO); got {endpoint!r} "
        f"— refusing to send credentials over cleartext\n"
    )
    sys.exit(2)


class S3CompatibleEndpointBackend(S3CompatibleBackend):
    label = "s3-compatible"

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        prefixer,
        static_prefix: str = "",
        region: str = "us-west-2",
    ):
        _validate_endpoint(endpoint)
        self._configure_prefix(prefixer, static_prefix)
        self._endpoint = endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,  # S3-compatible stores ignore it; required by boto3
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"},
                signature_version="s3v4",
            ),
        )

    @classmethod
    def from_env(cls) -> S3CompatibleEndpointBackend:
        who = "s3-compatible backend"
        return cls(
            endpoint=_required("ATIF_RELAY_S3_ENDPOINT", who),
            access_key=_required("ATIF_RELAY_S3_ACCESS_KEY", who),
            secret_key=_required("ATIF_RELAY_S3_SECRET_KEY", who),
            prefixer=build_prefixer(os.environ.get("ATIF_RELAY_PREFIXER", "none")),
            static_prefix=os.environ.get("ATIF_RELAY_KEY_PREFIX", ""),
            region=os.environ.get("ATIF_RELAY_S3_REGION", "us-west-2"),
        )

    def _probe(self) -> str:
        # Static creds are already in the client; just confirm endpoint shape.
        host = re.sub(r"^https?://", "", self._endpoint)
        return f"static creds endpoint={host}"
