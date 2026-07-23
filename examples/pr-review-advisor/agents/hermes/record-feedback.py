#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Persist explicitly approved review feedback through Hermes native memory."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from tools.memory_tool import MemoryStore

DISPOSITIONS = {"accepted", "dismissed", "corrected"}
PROFILE_ORIGINS = {"target_base", "operator_bootstrap"}


def bounded(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    result = " ".join(value.split())
    if len(result) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return result


def git_oid(value: object, label: str) -> str:
    result = bounded(value, label, 64)
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", result):
        raise ValueError(f"{label} must be a full lowercase Git object ID")
    return result


def digest(value: object, label: str) -> str:
    result = bounded(value, label, 64)
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return result


def canonical_repo_path(value: object, label: str, maximum: int = 4_096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} must be a nonempty bounded string")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a checkout-relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label} must be a canonical checkout-relative path")
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    ):
        raise ValueError(f"{label} contains a control character")
    portable = tuple(part.casefold().rstrip(" .") for part in parts)
    if any(not part for part in portable) or ".git" in portable:
        raise ValueError(f"{label} is not a portable review path")
    return value


def validate_review_scope(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "mode",
        "roots",
        "support_paths",
    }:
        raise ValueError("review_scope has an invalid shape")
    mode = value["mode"]
    if mode not in ("repository", "scoped"):
        raise ValueError("review_scope.mode is invalid")

    def paths(key: str) -> list[str]:
        raw = value[key]
        if not isinstance(raw, list) or len(raw) > 10_000:
            raise ValueError(f"review_scope.{key} must be a bounded array")
        normalized = [
            canonical_repo_path(item, f"review_scope.{key}[{index}]")
            for index, item in enumerate(raw)
        ]
        portable = [
            tuple(part.casefold().rstrip(" .") for part in path.split("/"))
            for path in normalized
        ]
        if normalized != sorted(normalized) or len(normalized) != len(
            set(normalized)
        ):
            raise ValueError(f"review_scope.{key} must be sorted and unique")
        if len(portable) != len(set(portable)):
            raise ValueError(f"review_scope.{key} has portable path collisions")
        return normalized

    roots = paths("roots")
    support_paths = paths("support_paths")
    if mode == "repository":
        if roots or support_paths:
            raise ValueError(
                "repository review scope requires empty roots and support_paths"
            )
    elif not roots:
        raise ValueError("scoped review scope requires at least one root")
    for index, root in enumerate(roots):
        if any(other.startswith(f"{root}/") for other in roots[index + 1 :]):
            raise ValueError("review_scope.roots must not overlap")
    for index, support in enumerate(support_paths):
        if any(
            other.startswith(f"{support}/")
            for other in support_paths[index + 1 :]
        ):
            raise ValueError("review_scope.support_paths must not overlap")
        if any(
            support == root
            or support.startswith(f"{root}/")
            or root.startswith(f"{support}/")
            for root in roots
        ):
            raise ValueError("review_scope support paths must not overlap roots")
    return {
        "mode": mode,
        "roots": roots,
        "support_paths": support_paths,
    }


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
        "review_scope",
        "scope_digest",
        "profile_path",
        "profile_origin",
        "profile_object_id",
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
    base = git_oid(payload["base_sha"], "base_sha")
    merge_base = git_oid(payload["merge_base_sha"], "merge_base_sha")
    head = git_oid(payload["head_sha"], "head_sha")
    profile = digest(payload["profile_digest"], "profile_digest")
    profile_source = git_oid(
        payload["profile_source_commit"],
        "profile_source_commit",
    )
    review_scope = validate_review_scope(payload["review_scope"])
    scope = digest(payload["scope_digest"], "scope_digest")
    expected_scope = hashlib.sha256(
        json.dumps(
            review_scope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(scope, expected_scope):
        raise ValueError("scope_digest does not match review_scope")
    profile_path = canonical_repo_path(payload["profile_path"], "profile_path")
    profile_origin = bounded(payload["profile_origin"], "profile_origin", 32)
    if profile_origin not in PROFILE_ORIGINS:
        raise ValueError(
            "profile_origin must be target_base or operator_bootstrap"
        )
    profile_object = git_oid(payload["profile_object_id"], "profile_object_id")
    acceptance_value = payload["acceptance_context_digest"]
    acceptance = (
        "-"
        if acceptance_value is None
        else digest(acceptance_value, "acceptance_context_digest")
    )
    context = digest(payload["context_digest"], "context_digest")
    candidate = bounded(payload["candidate_id"], "candidate_id", 64)
    disposition = bounded(payload["disposition"], "disposition", 32)
    if disposition not in DISPOSITIONS:
        raise ValueError("disposition must be accepted, dismissed, or corrected")
    lesson = bounded(payload["lesson"], "lesson", 700)
    evidence_digest = digest(payload["evidence_digest"], "evidence_digest")
    paths_value = payload["paths"]
    if not isinstance(paths_value, list) or len(paths_value) > 20:
        raise ValueError("paths must be an array with at most 20 entries")
    paths = [
        canonical_repo_path(value, f"paths[{index}]", maximum=256)
        for index, value in enumerate(paths_value)
    ]
    if review_scope["mode"] == "scoped":
        roots = review_scope["roots"]
        support_paths = review_scope["support_paths"]
        for path_value in paths:
            if not (
                any(
                    path_value == root or path_value.startswith(f"{root}/")
                    for root in roots
                )
                or any(
                    path_value == support
                    or path_value.startswith(f"{support}/")
                    for support in support_paths
                )
            ):
                raise ValueError(
                    "candidate path is outside the configured review scope: "
                    f"{path_value}"
                )

    memory_entry = lesson + (
        f" [repository={repository}; paths={','.join(paths) or '-'}; "
        f"candidate={candidate}; disposition={disposition}; "
        f"candidate_evidence={evidence_digest}; "
        f"base={base}; merge_base={merge_base}; head={head}; "
        f"profile={profile}; profile_source={profile_source}; "
        f"scope={scope}; profile_path={profile_path}; "
        f"profile_origin={profile_origin}; profile_object={profile_object}; "
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
