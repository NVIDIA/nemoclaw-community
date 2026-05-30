"""MinIO backend — boto3 with static creds + custom endpoint.

Local-development target. MinIO speaks the S3 wire format, so we use the
same boto3 S3 client with an explicit `endpoint_url` pointing at the MinIO
service and static admin credentials (no IMDS chain). Forces path-style
addressing since MinIO doesn't do virtual-hosted by default.
"""

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import os
import re
import sys

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .base import BackendError, BackendTransportError, PutResult, StorageBackend


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"required env var unset: {name} (minio backend)\n")
        sys.exit(2)
    return v


class MinioBackend(StorageBackend):
    label = "minio"

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
    ):
        self._endpoint = endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",  # MinIO doesn't care; required by boto3
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"},
                signature_version="s3v4",
            ),
        )

    @classmethod
    def from_env(cls) -> MinioBackend:
        return cls(
            endpoint=_required("MINIO_ENDPOINT"),
            access_key=_required("MINIO_ROOT_USER"),
            secret_key=_required("MINIO_ROOT_PASSWORD"),
        )

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None,
    ) -> PutResult:
        kwargs: dict[str, object] = {"Bucket": bucket, "Key": key, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: self._client.put_object(**kwargs)
            )
        except ClientError as e:
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500)
            code = e.response.get("Error", {}).get("Code", "Unknown")
            message = e.response.get("Error", {}).get("Message", str(e))
            raise BackendError(status, code, message) from e
        except Exception as e:  # noqa: BLE001 — any transport-level failure surfaces as 502
            raise BackendTransportError(str(e)) from e
        return PutResult(etag=result.get("ETag", ""))

    def health_probe(self) -> str:
        # Static creds are already in the client; just confirm endpoint shape.
        host = re.sub(r"^https?://", "", self._endpoint)
        return f"static minio admin endpoint={host}"
