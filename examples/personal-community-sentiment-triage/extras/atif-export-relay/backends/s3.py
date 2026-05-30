"""AWS S3 backend — boto3 + IMDS credentials chain.

Production target. Uses the standard boto3 credential chain (IMDS first,
then env, then config files), so the relay can run on an EC2 instance with
an IAM role attached and never need static credentials on disk. Region
comes from AWS_REGION; everything else is boto3's defaults.
"""

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import os
import sys

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .base import BackendError, BackendTransportError, PutResult, StorageBackend


class S3Backend(StorageBackend):
    label = "aws-s3"

    def __init__(self, region: str):
        self._region = region
        self._session = boto3.Session()
        self._client = self._session.client(
            "s3",
            region_name=region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    @classmethod
    def from_env(cls) -> S3Backend:
        region = os.environ.get("AWS_REGION")
        if not region:
            sys.stderr.write("required env var unset: AWS_REGION (s3 backend)\n")
            sys.exit(2)
        return cls(region=region)

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
        creds = self._session.get_credentials()
        if creds is None:
            raise RuntimeError("boto3 found no usable credentials in the IMDS/env/config chain")
        frozen = creds.get_frozen_credentials()
        return f"akid prefix={frozen.access_key[:8]}... region={self._region}"
