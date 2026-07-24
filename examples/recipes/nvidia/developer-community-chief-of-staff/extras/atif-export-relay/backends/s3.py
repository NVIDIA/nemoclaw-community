# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""AWS S3 backend — boto3 + IMDS credential chain.

Production target. Uses the standard boto3 credential chain (IMDS first, then
env, then config files), so the relay can run on an EC2 instance with an IAM
role attached and never need static credentials on disk. Region comes from
AWS_REGION; everything else is boto3's defaults.

All the S3-protocol mechanics (PutObject, error translation, key-prefix
lifecycle, logging) live in [s3_compatible.py](s3_compatible.py); only the
boto3 client (region + default creds) and the startup credential probe differ.

The object-key prefix is owned by the relay (not the sandbox):
`ATIF_RELAY_PREFIXER` (default `none`) selects the dynamic segment — `ec2-instance-id`
resolves the EC2 instance-id via IMDSv2 → `"<instance-id>/"`, for buckets whose
IAM policy scopes `s3:PutObject` to `<bucket>/<instance-id>/*`; `ATIF_RELAY_KEY_PREFIX`
is an optional literal appended after it. See [prefixers.py](prefixers.py).
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.client import Config

from .prefixers import build_prefixer
from .s3_compatible import S3CompatibleBackend


class S3Backend(S3CompatibleBackend):
    label = "aws-s3"

    def __init__(self, region: str, prefixer, static_prefix: str = ""):
        self._configure_prefix(prefixer, static_prefix)
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
        # Build (don't resolve) the prefixer here — from_env runs at module
        # import (relay builds the backend at import time), so any network
        # lookup must be deferred to health_probe(), which runs inside main()'s
        # fail-loud try/except. build_prefixer exits(2) on an unknown name.
        prefixer = build_prefixer(os.environ.get("ATIF_RELAY_PREFIXER", "none"))
        static_prefix = os.environ.get("ATIF_RELAY_KEY_PREFIX", "")
        return cls(region=region, prefixer=prefixer, static_prefix=static_prefix)

    def _probe(self) -> str:
        creds = self._session.get_credentials()
        if creds is None:
            raise RuntimeError("boto3 found no usable credentials in the IMDS/env/config chain")
        frozen = creds.get_frozen_credentials()
        return f"akid prefix={frozen.access_key[:8]}... region={self._region}"
