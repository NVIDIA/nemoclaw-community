# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Download, verify, and stage released OpenShift clients without a custom image."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import tarfile
import tempfile
from urllib.parse import urlsplit
import urllib.request


MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 64
CLIENTS = frozenset({"oc", "kubectl"})


def selected_artifact(machine: str | None = None) -> tuple[str, str]:
    architecture = {
        "x86_64": "AMD64",
        "amd64": "AMD64",
        "aarch64": "ARM64",
        "arm64": "ARM64",
    }.get((machine or platform.machine()).lower())
    if not architecture:
        raise SystemExit(f"unsupported node architecture: {(machine or platform.machine()).lower()}")
    url = os.environ[f"OPENSHIFT_CLI_{architecture}_URL"]
    expected = os.environ[f"OPENSHIFT_CLI_{architecture}_SHA256"]
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("OpenShift CLI URL must be an HTTPS artifact URL without credentials")
    if re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise SystemExit("invalid OpenShift CLI SHA-256")
    return url, expected


def load_binaries(archive_payload: bytes) -> dict[str, bytes]:
    """Read exactly one regular oc and kubectl from a bounded safe tarball."""
    if not archive_payload or len(archive_payload) > MAX_ARCHIVE_BYTES:
        raise SystemExit("OpenShift CLI archive has an invalid size")
    binaries: dict[str, bytes] = {}
    kubectl_alias = False
    expanded = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_payload), mode="r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise SystemExit("OpenShift CLI archive contains too many members")
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    not member.name
                    or path.is_absolute()
                    or ".." in path.parts
                    or "." in path.parts
                    or "\\" in member.name
                    or "\x00" in member.name
                    or member.issym()
                    or member.size < 0
                    or member.size > MAX_MEMBER_BYTES
                ):
                    raise SystemExit(f"unsafe archive member: {member.name}")
                if member.islnk():
                    # Official OpenShift client archives represent kubectl as
                    # an exact hardlink to the oc multicall binary. Do not
                    # materialize archive links; copy the verified oc bytes.
                    if path.parts != ("kubectl",) or member.linkname != "oc" or kubectl_alias:
                        raise SystemExit(f"unsafe archive member: {member.name}")
                    kubectl_alias = True
                    continue
                if not member.isfile() and not member.isdir():
                    raise SystemExit(f"unsafe archive member: {member.name}")
                expanded += member.size
                if expanded > MAX_EXPANDED_BYTES:
                    raise SystemExit("OpenShift CLI archive expands beyond 256 MiB")
                if path.name not in CLIENTS or not member.isfile():
                    continue
                if path.name in binaries:
                    raise SystemExit(f"duplicate OpenShift CLI executable: {path.name}")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise SystemExit(f"unable to read OpenShift CLI executable: {path.name}")
                payload = stream.read(MAX_MEMBER_BYTES + 1)
                if not payload or len(payload) != member.size:
                    raise SystemExit(f"invalid OpenShift CLI executable: {path.name}")
                binaries[path.name] = payload
    except (OSError, tarfile.TarError) as error:
        raise SystemExit("invalid OpenShift CLI archive") from error
    if kubectl_alias:
        if "kubectl" in binaries or "oc" not in binaries:
            raise SystemExit("invalid OpenShift CLI kubectl hardlink")
        binaries["kubectl"] = binaries["oc"]
    if set(binaries) != CLIENTS:
        missing = ", ".join(sorted(CLIENTS - set(binaries)))
        raise SystemExit(f"OpenShift CLI archive is missing required executables: {missing}")
    return binaries


def atomic_executable(destination: Path, payload: bytes) -> None:
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise SystemExit(f"invalid OpenShift CLI destination: {destination}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(
            stat.S_IRUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(destination: Path = Path("/cli-staging")) -> None:
    if destination.is_symlink() or not destination.is_dir():
        raise SystemExit("invalid OpenShift CLI staging directory")
    url, expected = selected_artifact()
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - HTTPS and checksum pinned.
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise SystemExit("OpenShift CLI archive exceeds 128 MiB")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise SystemExit(f"OpenShift CLI SHA-256 mismatch: expected {expected}, got {actual}")
    binaries = load_binaries(archive)
    for name in sorted(CLIENTS):
        atomic_executable(destination / name, binaries[name])
    print(f"staged OpenShift CLI {os.environ.get('OPENSHIFT_CLI_VERSION', 'unknown')} ({actual})")


if __name__ == "__main__":
    main()
