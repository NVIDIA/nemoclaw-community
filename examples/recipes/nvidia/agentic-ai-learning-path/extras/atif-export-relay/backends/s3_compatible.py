# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""S3-compatible backend base — shared boto3 mechanics + key-prefix lifecycle.

Both the real-AWS S3 backend and the local MinIO backend speak the S3 wire
protocol via boto3 and scope object keys with the same prefix model. This ABC
owns everything they share — the PutObject call, `ClientError` translation, the
key-prefix lifecycle, and per-request logging — so the concrete backends differ
only in how the boto3 client is built and what their startup probe reports.

Key-prefix model (the single place the contract lives):

    effective_key = prefixer.compute() + static_prefix + <bare key>

The producer (sandbox) emits **bare** keys; this layer is the sole owner of the
prefix. `prefixer` is a pluggable strategy (`ATIF_RELAY_PREFIXER`); `static_prefix`
is an optional literal (`ATIF_RELAY_KEY_PREFIX`). See [prefixers.py](prefixers.py).
The prefixer is resolved once at startup by `health_probe` (fail-loud) and
memoized, so `put_object` is a pure string op per request.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import Any

from botocore.exceptions import ClientError

from .base import BackendError, BackendTransportError, PutResult, StorageBackend
from .prefixers import KeyPrefixer, compose_key

log = logging.getLogger("atif-export-relay.backend")


class S3CompatibleBackend(StorageBackend):
    """Base for boto3 S3-protocol backends (real S3, MinIO).

    Subclasses set `self._client` (a boto3 s3 client) in `__init__`, call
    `self._configure_prefix(...)`, and implement `_probe()` and `from_env()`.
    `put_object` and `health_probe` are provided here and are identical across
    every S3-compatible backend.
    """

    _client: Any
    _prefixer: KeyPrefixer
    _static_prefix: str

    def _configure_prefix(self, prefixer: KeyPrefixer, static_prefix: str = "") -> None:
        self._prefixer = prefixer
        self._static_prefix = static_prefix

    def effective_key(self, key: str) -> str:
        """Compose the full object key from the relay-owned prefix + bare key.

        `compute()` is memoized (resolved at startup in `health_probe`), so this
        is just a string op per request. `effective_key("")` returns the prefix
        alone — used by `health_probe` to resolve + log it.
        """
        return compose_key(self._prefixer.compute() + self._static_prefix, key)

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None,
    ) -> PutResult:
        ekey = self.effective_key(key)
        # Authoritative per-attempt log: the EFFECTIVE key, on success or
        # failure (the relay handler logs only the incoming bare key).
        log.info("put backend=%s bucket=%s key=%s bytes=%d", self.label, bucket, ekey, len(body))
        kwargs: dict[str, object] = {"Bucket": bucket, "Key": ekey, "Body": body}
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
            # Carry the effective key so the relay's downstream_error warning
            # shows exactly what was rejected (prefix included).
            raise BackendError(status, code, f"{message} (key={ekey})") from e
        except Exception as e:  # noqa: BLE001 — any transport-level failure surfaces as 502
            raise BackendTransportError(str(e)) from e
        return PutResult(etag=result.get("ETag", ""), key=ekey)

    def health_probe(self) -> str:
        # Resolve the prefixer once at startup — fail-loud. compute() raises
        # PrefixerError on failure (e.g. IMDS unreachable), which main() turns
        # into sys.exit(1); better than silently writing unscoped keys. Then
        # delegate to the subclass's credential/endpoint probe.
        prefix = self.effective_key("")
        return f"{self._probe()} key_prefix={prefix or '(none)'}"

    @abstractmethod
    def _probe(self) -> str:
        """Return a short credential/endpoint string for the startup log.

        Raise on credential failure so the relay refuses to start.
        """
