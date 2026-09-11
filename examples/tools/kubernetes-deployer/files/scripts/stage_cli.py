# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Download, verify, and stage the released OpenShell CLI without building it."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import tarfile
import urllib.request


def selected_artifact() -> tuple[str, str]:
    machine = platform.machine().lower()
    architecture = {"x86_64": "AMD64", "amd64": "AMD64", "aarch64": "ARM64", "arm64": "ARM64"}.get(machine)
    if not architecture:
        raise SystemExit(f"unsupported node architecture: {machine}")
    return os.environ[f"OPENSHELL_CLI_{architecture}_URL"], os.environ[f"OPENSHELL_CLI_{architecture}_SHA256"]


def main() -> None:
    url, expected = selected_artifact()
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - URL is chart-pinned and schema-owned.
        archive = response.read(128 * 1024 * 1024 + 1)
    if len(archive) > 128 * 1024 * 1024:
        raise SystemExit("OpenShell CLI archive exceeds 128 MiB")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise SystemExit(f"OpenShell CLI SHA-256 mismatch: expected {expected}, got {actual}")

    executable: bytes | None = None
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise SystemExit(f"unsafe archive member: {member.name}")
            if path.name == "openshell" and member.isfile():
                source = bundle.extractfile(member)
                if source is None:
                    raise SystemExit("unable to read OpenShell executable")
                executable = source.read()
    if not executable:
        raise SystemExit("OpenShell archive does not contain an openshell executable")

    destination = Path("/tools/openshell")
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(executable)
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    temporary.replace(destination)
    print(f"staged OpenShell CLI {os.environ.get('OPENSHELL_CLI_VERSION', 'unknown')} ({actual})")


if __name__ == "__main__":
    main()
