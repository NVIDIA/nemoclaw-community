# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Install matching example-local OpenShell binaries without changing the host CLI."""

import hashlib
import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.1.6"
ROOT = Path(__file__).resolve().parent / ".cache/tools"


def download(name):
    path = ROOT / name
    if not path.exists():
        url = f"https://github.com/NVIDIA/OpenShell/releases/download/v{VERSION}/{name}"
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            path.with_suffix(".part").open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
        path.with_suffix(".part").replace(path)
    return path


def main():
    system = platform.system()
    machine = platform.machine()
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64"}.get(machine)
    if (
        system not in {"Linux", "Darwin"}
        or arch is None
        or (system == "Darwin" and arch != "aarch64")
    ):
        raise SystemExit("Use Linux x86_64/ARM64 or macOS Apple Silicon.")
    ROOT.mkdir(parents=True, exist_ok=True)
    for binary in ["openshell", "openshell-gateway"]:
        target = (
            f"{arch}-apple-darwin"
            if system == "Darwin"
            else f"{arch}-unknown-linux-{'gnu' if binary == 'openshell-gateway' else 'musl'}"
        )
        name = f"{binary}-{target}.tar.gz"
        sums = download(f"{binary}-checksums-sha256.txt").read_text()
        expected = next(
            line.split()[0] for line in sums.splitlines() if line.split()[-1].lstrip("*") == name
        )
        archive = download(name)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {name}")
        with tarfile.open(archive) as stream:
            member = stream.getmember(binary)
            if not member.isfile():
                raise ValueError("Expected a regular binary in the archive")
            with stream.extractfile(member) as source, (ROOT / binary).open("wb") as out:
                shutil.copyfileobj(source, out)
        (ROOT / binary).chmod(0o755)
    print(f"Verified OpenShell {VERSION} CLI and gateway in .cache/tools.")


if __name__ == "__main__":
    main()
