#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Persist explicitly approved review feedback through Hermes native memory."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from tools.memory_tool import MemoryStore

DISPOSITIONS = {"accepted", "dismissed", "corrected"}


def bounded(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    result = " ".join(value.split())
    if len(result) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return result


def main() -> int:
    if len(sys.argv) != 2:
        raise ValueError("usage: record-feedback.py PAYLOAD.json")
    path = Path(sys.argv[1])
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        raise ValueError("feedback payload must be a regular file no larger than 64 KiB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "repository",
        "base_sha",
        "merge_base_sha",
        "head_sha",
        "profile_digest",
        "profile_source_commit",
        "acceptance_context_digest",
        "context_digest",
        "candidate_id",
        "disposition",
        "lesson",
        "paths",
        "evidence_digest",
    }:
        raise ValueError("feedback payload has an invalid shape")

    repository = bounded(payload["repository"], "repository", 256)
    base = bounded(payload["base_sha"], "base_sha", 64)
    merge_base = bounded(payload["merge_base_sha"], "merge_base_sha", 64)
    head = bounded(payload["head_sha"], "head_sha", 64)
    profile = bounded(payload["profile_digest"], "profile_digest", 64)
    profile_source = bounded(
        payload["profile_source_commit"],
        "profile_source_commit",
        64,
    )
    acceptance_value = payload["acceptance_context_digest"]
    acceptance = (
        "-"
        if acceptance_value is None
        else bounded(acceptance_value, "acceptance_context_digest", 64)
    )
    context = bounded(payload["context_digest"], "context_digest", 64)
    candidate = bounded(payload["candidate_id"], "candidate_id", 64)
    disposition = bounded(payload["disposition"], "disposition", 32)
    if disposition not in DISPOSITIONS:
        raise ValueError("disposition must be accepted, dismissed, or corrected")
    lesson = bounded(payload["lesson"], "lesson", 700)
    evidence_digest = bounded(
        payload["evidence_digest"],
        "evidence_digest",
        64,
    )
    if (
        len(evidence_digest) != 64
        or any(character not in "0123456789abcdef" for character in evidence_digest)
    ):
        raise ValueError("evidence_digest must be a lowercase SHA-256 digest")
    paths_value = payload["paths"]
    if not isinstance(paths_value, list) or len(paths_value) > 20:
        raise ValueError("paths must be an array with at most 20 entries")
    paths = [bounded(value, "path", 256) for value in paths_value]

    memory_entry = lesson + (
        f" [repository={repository}; paths={','.join(paths) or '-'}; "
        f"candidate={candidate}; disposition={disposition}; "
        f"candidate_evidence={evidence_digest}; "
        f"base={base}; merge_base={merge_base}; head={head}; "
        f"profile={profile}; profile_source={profile_source}; "
        f"acceptance={acceptance}; context={context}]. "
        "Treat this as a hint and reverify it against current code."
    )
    if len(memory_entry) > 2_000:
        raise ValueError("curated lesson exceeds the Hermes built-in memory budget")

    store = MemoryStore()
    store.load_from_disk()
    result = store.add("memory", memory_entry)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"success": False, "error": str(error)}, sort_keys=True))
        raise SystemExit(1)
