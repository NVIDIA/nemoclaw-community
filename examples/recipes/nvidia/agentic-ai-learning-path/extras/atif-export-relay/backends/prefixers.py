# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Key-prefix strategies for the S3 backend.

The S3 backend composes its object-key prefix from two S3-only knobs:

    effective_prefix = prefixer.compute() + static_prefix

`prefixer` is one of the pluggable strategies below, selected by name at
startup (`ATIF_RELAY_PREFIXER`); `static_prefix` is a literal string
(`ATIF_RELAY_KEY_PREFIX`). The default prefixer is `none`, which contributes the
empty string, so the historical "static prefix only" behavior is unchanged.

These strategies are **S3-only**: MinIO has no instance-id semantics and the
generic relay handler never touches keys. Adding a strategy (hostname,
date-partition, tag-derived tenant, ...):

1. Subclass `KeyPrefixer` and implement `compute() -> str`.
2. Add `"<name>": <Class>` to `PREFIXERS` below.

`compute()` returns a prefix string (possibly empty). A strategy that depends on
a runtime lookup (e.g. IMDS) raises `PrefixerError` on failure rather than
returning "" — the relay's startup health probe turns that into a fail-loud
exit, which is preferable to silently writing objects outside the IAM-scoped
key path the instance role is allowed to write.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from botocore.utils import IMDSFetcher

# IMDS path for the EC2 instance-id. The base URL, IMDSv2 token, retries,
# timeouts, and AWS_EC2_METADATA_* env knobs are all owned by IMDSFetcher.
_INSTANCE_ID_PATH = "/latest/meta-data/instance-id"


class PrefixerError(RuntimeError):
    """A prefixer could not compute its prefix (e.g. IMDS unreachable).

    Raised from `compute()`. At startup it propagates out of the relay's
    `health_probe()` and aborts the process (fail-loud); it must never be
    swallowed into an empty prefix, which would write unscoped keys.
    """


def compose_key(prefix: str, key: str) -> str:
    """Join `prefix` + `key` into the final object key.

    `prefix` is expected to carry its own trailing slash (the ec2-instance-id
    strategy emits "<iid>/"; a static prefix should be written with a trailing
    "/" if a separator is wanted). Leading slashes on `key` are stripped so the
    join never doubles up. Empty `prefix` returns `key` unchanged.

    There is intentionally no "already-prefixed" idempotency guard: the producer
    (sandbox) emits **bare** keys and the relay is the sole owner of the prefix,
    so there is no second prefixing layer to dedupe against. A guard here would
    be false safety (it never caught the historical double-prefix bug — fixing
    the producer default did).
    """
    return f"{prefix}{key.lstrip('/')}"


class KeyPrefixer(ABC):
    """Strategy that computes the dynamic leading segment of an S3 key prefix.

    Subclasses set `name` (the `ATIF_RELAY_PREFIXER` selector value) and implement
    `compute()`.
    """

    name: str

    @abstractmethod
    def compute(self) -> str:
        """Return the dynamic prefix segment (may be empty).

        Contract (one place, so callers don't have to assemble it):
        - **Memoize** the first successful result — `compute()` is called once
          at startup by `S3CompatibleBackend.health_probe()` and again on every
          `put_object`; they must share one resolved value.
        - **Raise `PrefixerError` on hard failure**, never return "" — the
          startup probe turns that into a fail-loud process exit, which beats
          silently writing keys outside the IAM-scoped path.
        - **Resolved once per process.** A value derived from the host (e.g. the
          EC2 instance-id) is assumed stable for the process lifetime; the
          recovery path on instance replacement is a relay restart (which
          re-resolves). This matches the relay's `restart: unless-stopped`.
        """


class NonePrefixer(KeyPrefixer):
    """No dynamic segment — the effective prefix is just the static prefix."""

    name = "none"

    def compute(self) -> str:
        return ""


class Ec2InstanceIdPrefixer(KeyPrefixer):
    """Prefix every key with the EC2 instance-id: `"<instance-id>/"`.

    For buckets whose IAM policy scopes `s3:PutObject` to
    `arn:aws:s3:::<bucket>/<instance-id>/*`, so traces land under the path the
    host instance role is allowed to write.

    Uses botocore's `IMDSFetcher` — the same IMDS machinery boto3 already uses
    for the credential chain — so we get IMDSv2 token handling, retries/backoff,
    connect/read timeouts, IMDSv1 fallback, and the `AWS_EC2_METADATA_*` env
    knobs (endpoint override, IPv6 mode, disable) for free, rather than
    reimplementing them. botocore exposes no *public* instance-id getter (only
    region/credential helpers), so we call the `_`-prefixed request methods;
    they've been stable across the `boto3>=1.35,<2` range we pin. The result is
    memoized. Pass `fetcher` to inject a stub in tests.
    """

    name = "ec2-instance-id"

    def __init__(self, fetcher: IMDSFetcher | None = None):
        self._fetcher = fetcher if fetcher is not None else IMDSFetcher(num_attempts=3)
        self._cached: str | None = None

    def compute(self) -> str:
        if self._cached is None:
            self._cached = f"{self._fetch_instance_id()}/"
        return self._cached

    def _fetch_instance_id(self) -> str:
        try:
            token = self._fetcher._fetch_metadata_token()
            resp = self._fetcher._get_request(_INSTANCE_ID_PATH, None, token=token)
            instance_id = (getattr(resp, "text", "") or "").strip()
        except Exception as e:  # noqa: BLE001 — any IMDS failure is fail-loud
            raise PrefixerError(f"could not resolve EC2 instance-id from IMDS: {e}") from e
        if not instance_id:
            raise PrefixerError("IMDS returned an empty instance-id")
        return instance_id


PREFIXERS: dict[str, type[KeyPrefixer]] = {
    NonePrefixer.name: NonePrefixer,
    Ec2InstanceIdPrefixer.name: Ec2InstanceIdPrefixer,
}


def build_prefixer(name: str) -> KeyPrefixer:
    """Instantiate the prefixer selected by `name` (mirrors `build_backend`)."""
    cls = PREFIXERS.get(name)
    if cls is None:
        sys.stderr.write(
            f"unsupported ATIF_RELAY_PREFIXER: {name!r} "
            f"(available: {sorted(PREFIXERS)})\n"
        )
        sys.exit(2)
    return cls()
