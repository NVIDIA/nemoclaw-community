# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Generate bindings from checksum-verified public OpenShell v0.1.6 schemas."""

import hashlib
import importlib.resources
import subprocess
import sys
import urllib.request
from pathlib import Path

REVISION = "ac7f615cd12d5cc49cb16eb1f5f10ffeb1e90f47"
SCHEMAS = {
    "supervisor_middleware.proto": (
        "b3c2037a6b51285b48a39025b85e79a4c717a2b95accb89cf43dbe6079831c75"
    ),
    "extension.proto": "60f28ee9dc846d41152f4db7e82a439c78d024786efaceb464900d1d1ad129ad",
}
ROOT = Path(__file__).resolve().parent


def main():
    source = ROOT / ".cache/proto"
    output = ROOT / ".cache/bindings"
    source.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    for name, expected in SCHEMAS.items():
        path = source / name
        if not path.exists():
            url = f"https://raw.githubusercontent.com/NVIDIA/OpenShell/{REVISION}/proto/{name}"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(1024 * 1024)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Checksum mismatch for {name}")
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for cached {name}")
    include = importlib.resources.files("grpc_tools") / "_proto"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{source}",
            f"-I{include}",
            f"--python_out={output}",
            f"--grpc_python_out={output}",
            *[str(source / name) for name in SCHEMAS],
        ],
        check=True,
    )
    print("OpenShell v0.1.6 middleware bindings verified and generated.")


if __name__ == "__main__":
    main()
