# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Storage-backend ABC + error types for atif-export-relay.

Every backend (S3, MinIO, and any future Azure/GCS/custom) implements the
`StorageBackend` interface below. The relay's HTTP handler is backend-agnostic:
it parses auth + path, hands `(bucket, key, body, content_type)` to whichever
backend was selected at startup, and translates the result back into an HTTP
response.

Adding a new backend (e.g. Azure Blob, GCS, a custom non-S3 endpoint):
1. Create `backends/<name>.py` with `class <Name>Backend(StorageBackend)`.
2. Add its SDK to the relay's Dockerfile pip install.
3. Add `"<name>": <Name>Backend` to BACKENDS in `backends/__init__.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PutResult:
    """Backend result for a successful PutObject.

    `etag` is required by nemo-relay's object_store S3 client — a missing
    ETag header in the relay's 200 response causes object_store to record
    `Error::MissingEtag`, which then permanently disables the sink for the
    rest of the process lifetime. Backends that don't natively produce an
    ETag should synthesize one (e.g. MD5 of the body) rather than returning
    "".

    `key` is the effective object key the backend actually wrote (after any
    prefixing). The relay logs it on success so the operator sees the real
    destination, not the bare key the sandbox sent.
    """

    etag: str
    key: str = ""


class BackendError(Exception):
    """Application-layer error from a storage backend.

    Maps directly to the HTTP status returned to the upstream client.
    Use for 4xx-style "your request was understood and rejected" cases
    (NoSuchBucket, AccessDenied, etc.).
    """

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class BackendTransportError(Exception):
    """Transport/connectivity failure reaching the downstream.

    Maps to 502 Bad Gateway. Use for socket errors, DNS failures, TLS
    handshake failures, etc. — anything that prevented the request from
    being processed by the downstream at all.
    """


class StorageBackend(ABC):
    """Abstract backend interface.

    Subclasses must set `label` (used in startup/access logs) and implement
    `from_env`, `put_object`, and `health_probe`.
    """

    label: str

    @classmethod
    @abstractmethod
    def from_env(cls) -> StorageBackend:
        """Build the backend from process env vars.

        Each backend reads only the vars it needs. Missing required vars
        should call `sys.exit(2)` with a clear message — startup-time
        failure is preferable to a runtime KeyError on the first request.
        """

    @abstractmethod
    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None,
    ) -> PutResult:
        """Upload `body` to `bucket/key`. Returns the ETag (or equivalent).

        Raise `BackendError(status, code, message)` for application errors,
        `BackendTransportError(str(e))` for transport failures. Anything
        else will surface as a 500 to the caller.
        """

    @abstractmethod
    def health_probe(self) -> str:
        """Synchronous credential check, called once at startup.

        Returns a short human-readable string for the startup log
        (e.g. "akid prefix=AKIA1234..."). Raises on credential failure
        so the relay refuses to start if creds aren't usable.
        """
