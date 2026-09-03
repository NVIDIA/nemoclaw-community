#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Build the focused, first-party SRE skill bundle reproducibly."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile


ALLOWED_ROOTS = frozenset({"kubernetes-sre", "openshift-llm-deploy"})
REQUIRED_FILES = frozenset(
    {
        "kubernetes-sre/SKILL.md",
        "openshift-llm-deploy/SKILL.md",
    }
)
EXCLUDED_PREFIXES: tuple[str, ...] = ()
RUNTIME_SUPPORT_DIRECTORIES = frozenset(
    {"scripts", "templates", "tools", "workflows", "resources"}
)
LEGAL_FILENAMES = frozenset(
    {"LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md", "SOURCE_NOTICES.md"}
)
MAX_FILES = 1024
MAX_FILE_BYTES = 2_097_152
MAX_EXPANDED_BYTES = 8_388_608
MAX_ARCHIVE_BYTES = 360_000
PART_BYTES = 240_000
RUNTIME_SAFETY_MARKER = "<!-- nemoclaw-runtime-safety-v1 -->"
RUNTIME_SAFETY = f"""
{RUNTIME_SAFETY_MARKER}
## NemoClaw runtime safety

The chart's safety policy overrides conflicting examples in this skill.
Use `/chart-bin/oc --kubeconfig "$SRE_KUBECONFIG"` for cluster requests.
Inspect current state first. Obtain explicit user approval before any cluster
create, update, or patch. Never read or reveal Secrets, tokens, credentials, or
private keys. Never delete cluster or external-system resources, grant RBAC or
SCC access, impersonate identities, or grant cluster-admin. Refuse destructive
requests and provide a human-reviewable command instead.
Never build or publish custom images, and never use mutable image tags; require
an operator-approved existing image pinned by digest. The only exception to the
deletion rule is an exact model resource pre-authorized through the chart's
optional, namespace-scoped model-deletion proxy.
""".encode("utf-8")


def is_runtime_payload(relative: PurePosixPath) -> bool:
    """Keep every skill entrypoint plus executable/runtime support material."""
    lowered_parts = {part.lower() for part in relative.parts}
    return bool(
        relative.name == "SKILL.md"
        or relative.name in LEGAL_FILENAMES
        or lowered_parts.intersection(RUNTIME_SUPPORT_DIRECTORIES)
        or (
            relative.parts[0] == "openshift-llm-deploy"
            and "references" in lowered_parts
        )
    )


def apply_runtime_safety(name: str, payload: bytes) -> bytes:
    """Add the same safety contract to every executable skill prompt."""
    if not name.endswith("/SKILL.md"):
        return payload
    if RUNTIME_SAFETY_MARKER.encode("utf-8") in payload:
        raise SystemExit(f"skill source already contains runtime safety marker: {name}")
    if not payload.startswith(b"---\n"):
        raise SystemExit(f"skill source is missing YAML frontmatter: {name}")
    frontmatter_end = payload.find(b"\n---\n", 4)
    if frontmatter_end < 0:
        raise SystemExit(f"skill source has invalid YAML frontmatter: {name}")
    insertion = frontmatter_end + len(b"\n---\n")
    return payload[:insertion] + b"\n" + RUNTIME_SAFETY + b"\n" + payload[insertion:]


def checked_payloads(source: Path) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    expanded = 0
    for path in sorted(source.rglob("*")):
        name = path.relative_to(source).as_posix()
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise SystemExit(f"unsafe skill path: {name}")
        if not relative.parts or relative.parts[0] not in ALLOWED_ROOTS:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if name.endswith(".pyc") or name.startswith(EXCLUDED_PREFIXES):
            continue
        if not is_runtime_payload(relative):
            continue
        if path.is_symlink():
            raise SystemExit(f"skill source must not contain links: {name}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SystemExit(f"skill source must contain only regular files: {name}")
        payload = path.read_bytes()
        if not payload:
            raise SystemExit(f"skill source is empty: {name}")
        if len(payload) > MAX_FILE_BYTES:
            raise SystemExit(f"skill source file is too large: {name}")
        if b"\x00" in payload:
            raise SystemExit(f"skill source must be text: {name}")
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SystemExit(f"skill source must be UTF-8: {name}") from error
        payload = apply_runtime_safety(name, payload)
        expanded += len(payload)
        if expanded > MAX_EXPANDED_BYTES:
            raise SystemExit("expanded SRE skill source exceeds the configured limit")
        payloads[name] = payload
        if len(payloads) > MAX_FILES:
            raise SystemExit("SRE skill source contains too many files")
    missing = REQUIRED_FILES - set(payloads)
    if missing:
        raise SystemExit(f"missing required skill files: {', '.join(sorted(missing))}")
    return payloads


def member(name: str, payload: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o555 if "/scripts/" in f"/{name}" else 0o444
    return info


def build(
    source: Path,
    parts_directory: Path,
    parts_index_destination: Path,
    digest_destination: Path,
    manifest_digest_destination: Path,
    archive_destination: Path | None = None,
) -> str:
    payloads = checked_payloads(source)
    manifest = (
        "\n".join(
            f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
            for name in sorted(payloads)
        )
        + "\n"
    ).encode("utf-8")

    uncompressed = io.BytesIO()
    with tarfile.open(fileobj=uncompressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(payloads):
            archive.addfile(member(name, payloads[name]), io.BytesIO(payloads[name]))
        archive.addfile(member("MANIFEST.sha256", manifest), io.BytesIO(manifest))
    archive_bytes = lzma.compress(
        uncompressed.getvalue(),
        format=lzma.FORMAT_XZ,
        preset=9 | lzma.PRESET_EXTREME,
    )
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise SystemExit(
            f"SRE archive is {len(archive_bytes)} bytes; keep it below the configured limit"
        )
    parts_directory.mkdir(parents=True, exist_ok=True)
    expected_part_names: set[str] = set()
    parts: list[dict[str, object]] = []
    for index, offset in enumerate(range(0, len(archive_bytes), PART_BYTES)):
        name = f"sre-skills.part-{index:03d}"
        expected_part_names.add(name)
        payload = archive_bytes[offset : offset + PART_BYTES]
        (parts_directory / name).write_bytes(payload)
        parts.append(
            {
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        )
    for stale in parts_directory.glob("sre-skills.part-*"):
        if stale.name not in expected_part_names:
            stale.unlink()
    parts_index_destination.write_text(
        json.dumps({"parts": parts, "version": 1}, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    if archive_destination is not None:
        archive_destination.write_bytes(archive_bytes)
    digest = hashlib.sha256(archive_bytes).hexdigest()
    digest_destination.write_text(digest + "\n", encoding="utf-8")
    manifest_digest_destination.write_text(
        hashlib.sha256(manifest).hexdigest() + "\n",
        encoding="utf-8",
    )
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    chart = Path(__file__).resolve().parents[1]
    parser.add_argument("--source", type=Path, default=chart / "files" / "skills")
    parser.add_argument("--parts-directory", type=Path, default=chart / "files")
    parser.add_argument(
        "--parts-index-output",
        type=Path,
        default=chart / "files" / "sre-skills.parts.json",
    )
    parser.add_argument(
        "--digest-output",
        type=Path,
        default=chart / "files" / "sre-skills.tar.xz.sha256",
    )
    parser.add_argument(
        "--manifest-digest-output",
        type=Path,
        default=chart / "files" / "sre-skills.manifest.sha256",
    )
    parser.add_argument("--archive-output", type=Path)
    arguments = parser.parse_args()
    print(
        build(
            arguments.source,
            arguments.parts_directory,
            arguments.parts_index_output,
            arguments.digest_output,
            arguments.manifest_digest_output,
            arguments.archive_output,
        )
    )


if __name__ == "__main__":
    main()
