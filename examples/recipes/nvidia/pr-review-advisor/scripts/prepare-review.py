#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Prepare a non-executing, exact-SHA review payload on the trusted host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STATUS_RE = re.compile(r"^(?:[AMDTUXB]|[RC][0-9]{1,3})$")
DEFAULT_PROFILE_REPO_PATH = ".nemoclaw/review-advisor/profile.yaml"
PROFILE_SOURCE_RE = re.compile(
    r'^ {2}source_commit:\s*["\']?([0-9a-f]{40})["\']?\s*(?:#.*)?$',
    re.MULTILINE,
)
MAX_PROFILE_BYTES = 1024 * 1024
MAX_ACCEPTANCE_CONTEXT_BYTES = 512 * 1024
MAX_ACCEPTANCE_TITLE_BYTES = 1024
MAX_ACCEPTANCE_PR_BODY_BYTES = 128 * 1024
MAX_ACCEPTANCE_ISSUE_BODY_BYTES = 64 * 1024
MAX_ACCEPTANCE_ISSUES = 10
ACCEPTANCE_SCHEMA_VERSION = "review-advisor/pr-acceptance/v1"
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OBJECT_ID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
DEFAULT_MAX_CHECKOUT_FILES = 50_000
DEFAULT_MAX_CHECKOUT_BYTES = 512 * 1024 * 1024
MAX_CHECKOUT_FILES = 1_000_000
MAX_CHECKOUT_BYTES = 8 * 1024 * 1024 * 1024
MAX_GIT_PATH_BYTES = 4096
MAX_TREE_RECORD_BYTES = MAX_GIT_PATH_BYTES + 256
MAX_GIT_ERROR_BYTES = 16 * 1024
STREAM_CHUNK_BYTES = 64 * 1024


class PreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_id: str
    size: int
    path: str


@dataclass(frozen=True)
class ReviewScope:
    """Canonical host-authorized review and evidence boundaries."""

    mode: str
    roots: tuple[str, ...]
    support_paths: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "roots": list(self.roots),
            "support_paths": list(self.support_paths),
        }

    def allows_change(self, path: str) -> bool:
        if self.mode == "repository":
            return True
        return any(path == root or path.startswith(f"{root}/") for root in self.roots)

    def allows_read(self, path: str) -> bool:
        return self.allows_change(path) or any(
            path == support or path.startswith(f"{support}/")
            for support in self.support_paths
        )


def git_env(*, attr_source: str | None = None) -> dict[str, str]:
    # Git has many environment overrides for its repository, object database,
    # config, worktree, and graph state. None of those ambient overrides are
    # part of the trusted review input. Keep ordinary process settings such as
    # PATH and HOME, then install only the Git controls used here.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_")
    }
    env.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
    )
    if attr_source is not None:
        env["GIT_ATTR_SOURCE"] = attr_source
    return env


def git_command(repo: Path, *args: str) -> list[str]:
    return [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "submodule.recurse=false",
        "-c",
        "diff.external=",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "diff.algorithm=myers",
        "-c",
        "diff.indentHeuristic=false",
        "-c",
        "diff.renameLimit=1000",
        "-C",
        str(repo),
        *args,
    ]


def git_error(command: list[str], stderr: Any) -> str:
    stderr.seek(0)
    detail = stderr.read(MAX_GIT_ERROR_BYTES + 1)
    truncated = len(detail) > MAX_GIT_ERROR_BYTES
    text = detail[:MAX_GIT_ERROR_BYTES].decode("utf-8", "replace").strip()
    if truncated:
        text += " [stderr truncated]"
    suffix = f": {text}" if text else ""
    return f"Git command failed ({' '.join(command[1:])}){suffix}"


def git(repo: Path, *args: str, text: bool = False) -> bytes | str:
    command = git_command(repo, *args)
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=git_env(),
        text=text,
    )
    if result.returncode != 0:
        stderr = (
            result.stderr.strip()
            if text
            else result.stderr.decode("utf-8", "replace").strip()
        )
        raise PreparationError(f"Git command failed ({' '.join(command[1:])}): {stderr}")
    return result.stdout


def bounded_git_output(
    repo: Path,
    *args: str,
    maximum: int,
    label: str,
    attr_source: str | None = None,
) -> bytes:
    """Capture Git stdout while failing as soon as its byte budget is exceeded."""

    if maximum < 0:
        raise PreparationError(f"{label} has no remaining byte budget")
    command = git_command(repo, *args)
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=git_env(attr_source=attr_source),
        )
        assert process.stdout is not None
        captured = bytearray()
        try:
            while True:
                allowance = maximum - len(captured)
                chunk = process.stdout.read(min(STREAM_CHUNK_BYTES, allowance + 1))
                if not chunk:
                    break
                captured.extend(chunk)
                if len(captured) > maximum:
                    process.kill()
                    process.wait()
                    raise PreparationError(
                        f"{label} exceeds the configured {maximum}-byte capture limit"
                    )
            returncode = process.wait()
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        if returncode != 0:
            raise PreparationError(git_error(command, stderr))
    return bytes(captured)


def full_sha(value: str, label: str) -> str:
    value = value.strip().lower()
    if not SHA_RE.fullmatch(value):
        raise PreparationError(f"{label} must be a full lowercase 40-character commit SHA")
    return value


def safe_path(raw: bytes) -> str:
    if len(raw) > MAX_GIT_PATH_BYTES:
        raise PreparationError(
            f"Git path exceeds the {MAX_GIT_PATH_BYTES}-byte fail-closed limit"
        )
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise PreparationError("Git path is not valid UTF-8") from exc
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\x00" in value
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or str(path) != value
        or any(part in ("", ".") for part in path.parts)
    ):
        raise PreparationError(f"Unsafe Git path: {value!r}")
    portable_parts = [
        unicodedata.normalize("NFC", part).casefold().rstrip(" .")
        for part in path.parts
    ]
    if any(not part for part in portable_parts):
        raise PreparationError(f"Git path has an empty portable component: {value!r}")
    if any(part == ".git" for part in portable_parts):
        raise PreparationError(
            f"Git path collides with reserved review metadata: {value!r}"
        )
    return value


def portable_path_key(path: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFC", component).casefold().rstrip(" .")
        for component in PurePosixPath(path).parts
    )


def normalize_scope_paths(values: list[str], label: str) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    portable: dict[tuple[str, ...], str] = {}
    for value in values:
        try:
            path = safe_path(value.encode("utf-8", "strict"))
        except (UnicodeEncodeError, PreparationError) as exc:
            raise PreparationError(f"{label} contains an invalid repository path") from exc
        if path in seen:
            raise PreparationError(f"{label} contains duplicate paths")
        key = portable_path_key(path)
        prior = portable.get(key)
        if prior is not None:
            raise PreparationError(
                f"{label} contains paths that collide on a portable filesystem"
            )
        seen.add(path)
        portable[key] = path
        normalized.append(path)
    return tuple(sorted(normalized))


def review_scope_from_args(
    scope_roots: list[str],
    support_paths: list[str],
) -> ReviewScope:
    roots = normalize_scope_paths(scope_roots, "--scope-root")
    supports = normalize_scope_paths(support_paths, "--support-path")
    if not roots:
        if supports:
            raise PreparationError("--support-path requires at least one --scope-root")
        return ReviewScope(mode="repository", roots=(), support_paths=())

    for index, root in enumerate(roots):
        if any(
            other.startswith(f"{root}/")
            for other in roots[index + 1 :]
        ):
            raise PreparationError("--scope-root paths must not overlap")
    for index, support in enumerate(supports):
        if any(
            other.startswith(f"{support}/")
            for other in supports[index + 1 :]
        ):
            raise PreparationError("--support-path paths must not overlap")
        if any(
            support == root
            or support.startswith(f"{root}/")
            or root.startswith(f"{support}/")
            for root in roots
        ):
            raise PreparationError(
                "--support-path paths must not overlap --scope-root paths"
            )
    return ReviewScope(mode="scoped", roots=roots, support_paths=supports)


def canonical_scope_bytes(scope: ReviewScope) -> bytes:
    return json.dumps(
        scope.as_json(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_exact_attribute_source(repo: Path, head: str, probe_path: str) -> None:
    """Require exact-tree attributes and reject local info/attributes overrides."""

    attributes_path_text = str(
        git(repo, "rev-parse", "--git-path", "info/attributes", text=True)
    ).strip()
    attributes_path = Path(attributes_path_text)
    if not attributes_path.is_absolute():
        attributes_path = repo / attributes_path
    if attributes_path.exists() or attributes_path.is_symlink():
        info = attributes_path.lstat()
        if (
            attributes_path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_size != 0
        ):
            raise PreparationError(
                "Local Git info/attributes could change the exact-tree patch; "
                f"remove or empty {attributes_path}"
            )

    # Fail clearly on Git versions that cannot bind attributes to a tree-ish.
    bounded_git_output(
        repo,
        "check-attr",
        f"--source={head}",
        "--all",
        "--",
        probe_path,
        maximum=64 * 1024,
        label="Exact-tree Git attribute probe",
        attr_source=head,
    )


def git_metadata_path(repo: Path, relative: str) -> Path:
    """Resolve one Git metadata path and require it to stay in this repository."""

    path_text = str(git(repo, "rev-parse", "--git-path", relative, text=True)).strip()
    path = Path(path_text)
    if not path.is_absolute():
        path = repo / path

    roots: list[Path] = []
    for arguments in (("--absolute-git-dir",), ("--git-common-dir",)):
        root_text = str(git(repo, "rev-parse", *arguments, text=True)).strip()
        root = Path(root_text)
        if not root.is_absolute():
            root = repo / root
        roots.append(root.resolve(strict=True))

    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root)
            return path
        except ValueError:
            continue
    raise PreparationError(
        f"Git metadata path for {relative} escapes this repository: {path}"
    )


def validate_exact_graph_source(repo: Path) -> None:
    """Reject local Git state that can rewrite or hide commit ancestry."""

    grafts_path = git_metadata_path(repo, "info/grafts")
    if grafts_path.exists() or grafts_path.is_symlink():
        info = grafts_path.lstat()
        if (
            grafts_path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_size != 0
        ):
            raise PreparationError(
                "Local Git info/grafts could change exact commit ancestry; "
                f"remove or empty {grafts_path}"
            )

    shallow = str(
        git(repo, "rev-parse", "--is-shallow-repository", text=True)
    ).strip()
    if shallow == "true":
        raise PreparationError(
            "Exact merge-base validation requires a complete, non-shallow repository; "
            "fetch full history before preparing the review"
        )
    if shallow != "false":
        raise PreparationError(
            f"Git returned an invalid shallow-repository state: {shallow!r}"
        )


def canonical_repository_from_url(value: str) -> str | None:
    value = value.strip()
    path = ""
    if value.startswith("git@github.com:"):
        path = value.split(":", 1)[1]
    elif value.startswith(("https://github.com/", "ssh://git@github.com/")):
        path = urlparse(value).path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path if REPOSITORY_RE.fullmatch(path) else None


def load_event(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise PreparationError(f"Event must be a regular non-symlink file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Invalid event JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PreparationError("Event JSON must be an object")
    return value


def exact_object(
    value: Any,
    label: str,
    *,
    required: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreparationError(f"{label} must be an object")
    expected = set(required)
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise PreparationError(f"{label} is missing: {', '.join(missing)}")
    if unknown:
        raise PreparationError(f"{label} has unknown fields: {', '.join(unknown)}")
    return value


def bounded_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise PreparationError(f"{label} must be text")
    if not empty and not value.strip():
        raise PreparationError(f"{label} must be nonempty")
    if len(value.encode("utf-8")) > maximum:
        raise PreparationError(f"{label} exceeds the {maximum}-byte limit")
    return value


def timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise PreparationError(f"{label} is not a canonical GitHub UTC timestamp")
    return value


def positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 1 or value > 2_147_483_647:
        raise PreparationError(f"{label} must be a positive integer")
    return value


def load_acceptance_context(
    path: Path,
    *,
    repository: str,
    pull_request_number: int | None,
    base_sha: str,
    head_sha: str,
) -> tuple[dict[str, Any], str]:
    """Load and normalize one trusted-host current-PR acceptance snapshot."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise PreparationError(f"Cannot inspect acceptance context: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise PreparationError("Acceptance context must be a regular non-symlink file")
    if info.st_size > MAX_ACCEPTANCE_CONTEXT_BYTES:
        raise PreparationError("Acceptance context exceeds the 512 KiB limit")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_ACCEPTANCE_CONTEXT_BYTES:
            raise PreparationError("Acceptance context exceeds the 512 KiB limit")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreparationError("Acceptance context is not valid UTF-8 JSON") from exc
    obj = exact_object(
        value,
        "acceptance context",
        required=(
            "schema_version",
            "source",
            "repository",
            "pull_request_number",
            "base_sha",
            "head_sha",
            "pull_request",
            "closing_issues",
        ),
    )
    if obj["schema_version"] != ACCEPTANCE_SCHEMA_VERSION:
        raise PreparationError("Acceptance context schema_version is unsupported")
    source = exact_object(
        obj["source"],
        "acceptance context source",
        required=(
            "kind",
            "mutable_review_comments_included",
            "closing_link_detection",
        ),
    )
    if source != {
        "kind": "github-rest-current-pr",
        "mutable_review_comments_included": False,
        "closing_link_detection": "explicit-body-keywords",
    }:
        raise PreparationError(
            "Acceptance context source must be the current-PR REST snapshot "
            "without mutable review comments"
        )
    actual_repository = obj["repository"]
    if (
        not isinstance(actual_repository, str)
        or not REPOSITORY_RE.fullmatch(actual_repository)
        or actual_repository.casefold() != repository.casefold()
    ):
        raise PreparationError("Acceptance context repository does not match the review")
    actual_number = positive_integer(
        obj["pull_request_number"],
        "acceptance context pull_request_number",
    )
    if pull_request_number is None or actual_number != pull_request_number:
        raise PreparationError(
            "Acceptance context pull_request_number does not match the review"
        )
    if full_sha(obj["base_sha"], "acceptance context base SHA") != base_sha:
        raise PreparationError("Acceptance context base_sha does not match the review")
    if full_sha(obj["head_sha"], "acceptance context head SHA") != head_sha:
        raise PreparationError("Acceptance context head_sha does not match the review")
    pull = exact_object(
        obj["pull_request"],
        "acceptance context pull_request",
        required=("title", "body", "updated_at"),
    )
    normalized_pull = {
        "title": bounded_text(
            pull["title"],
            "acceptance context PR title",
            maximum=MAX_ACCEPTANCE_TITLE_BYTES,
            empty=False,
        ),
        "body": bounded_text(
            pull["body"],
            "acceptance context PR body",
            maximum=MAX_ACCEPTANCE_PR_BODY_BYTES,
        ),
        "updated_at": timestamp(
            pull["updated_at"],
            "acceptance context PR updated_at",
        ),
    }
    issues = obj["closing_issues"]
    if not isinstance(issues, list) or len(issues) > MAX_ACCEPTANCE_ISSUES:
        raise PreparationError(
            f"Acceptance context closing_issues must contain at most "
            f"{MAX_ACCEPTANCE_ISSUES} items"
        )
    normalized_issues: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, value in enumerate(issues):
        issue = exact_object(
            value,
            f"acceptance context closing_issues[{index}]",
            required=("number", "title", "body", "state", "updated_at"),
        )
        number = positive_integer(
            issue["number"],
            f"acceptance context closing_issues[{index}].number",
        )
        if number in seen:
            raise PreparationError(f"Acceptance context repeats closing issue #{number}")
        seen.add(number)
        state = issue["state"]
        if state not in ("open", "closed"):
            raise PreparationError(
                f"Acceptance context closing_issues[{index}].state is invalid"
            )
        normalized_issues.append(
            {
                "number": number,
                "title": bounded_text(
                    issue["title"],
                    f"acceptance context closing_issues[{index}].title",
                    maximum=MAX_ACCEPTANCE_TITLE_BYTES,
                    empty=False,
                ),
                "body": bounded_text(
                    issue["body"],
                    f"acceptance context closing_issues[{index}].body",
                    maximum=MAX_ACCEPTANCE_ISSUE_BODY_BYTES,
                ),
                "state": state,
                "updated_at": timestamp(
                    issue["updated_at"],
                    f"acceptance context closing_issues[{index}].updated_at",
                ),
            }
        )
    normalized = {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "source": source,
        "repository": repository,
        "pull_request_number": actual_number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pull_request": normalized_pull,
        "closing_issues": normalized_issues,
    }
    canonical = (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return normalized, hashlib.sha256(canonical).hexdigest()


def event_values(event: dict[str, Any]) -> tuple[str, str, str, int]:
    try:
        pull = event["pull_request"]
        base = full_sha(pull["base"]["sha"], "event base SHA")
        head = full_sha(pull["head"]["sha"], "event head SHA")
        repository = pull["base"]["repo"]["full_name"]
        number = int(pull["number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreparationError("Event is not a complete GitHub pull_request payload") from exc
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise PreparationError("Event repository identity is invalid")
    if number < 1:
        raise PreparationError("Event pull request number is invalid")
    return base, head, repository, number


def require_commit(repo: Path, sha: str, label: str) -> None:
    try:
        object_type = bounded_git_output(
            repo,
            "cat-file",
            "-t",
            sha,
            maximum=64,
            label=f"{label} object type",
        ).strip()
    except PreparationError as exc:
        raise PreparationError(
            f"{label} commit {sha} is not present locally; fetch the exact PR refs first"
        ) from exc
    if object_type != b"commit":
        rendered_type = object_type.decode("ascii", "replace") or "unknown"
        raise PreparationError(
            f"{label} SHA {sha} must identify a commit object directly; "
            f"found {rendered_type}"
        )


def unique_merge_base(repo: Path, base: str, head: str) -> str:
    """Return the one unambiguous merge base for the exact target and head."""

    try:
        raw = str(git(repo, "merge-base", "--all", base, head, text=True))
    except PreparationError as exc:
        raise PreparationError(
            "The exact base and head do not have one locally available merge base"
        ) from exc
    candidates = [line.strip().lower() for line in raw.splitlines() if line.strip()]
    if len(candidates) != 1:
        raise PreparationError(
            "The exact base and head must have one unambiguous merge base; "
            f"git merge-base --all returned {len(candidates)}"
        )
    return full_sha(candidates[0], "merge base SHA")


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=git_env(),
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = result.stderr.decode("utf-8", "replace").strip()
    raise PreparationError(
        "Could not validate profile calibration ancestry"
        + (f": {detail}" if detail else "")
    )


def parse_tree_record(record: bytes) -> TreeEntry:
    try:
        metadata, raw_path = record.split(b"\t", 1)
        mode_raw, type_raw, object_id_raw, size_raw = metadata.split(b" ", 3)
        mode = mode_raw.decode("ascii", "strict")
        object_type = type_raw.decode("ascii", "strict")
        object_id = object_id_raw.decode("ascii", "strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PreparationError("Git returned malformed tree metadata") from exc
    path = safe_path(raw_path)
    if mode == "120000":
        raise PreparationError(f"Review inputs with Git symlinks are not supported: {path}")
    if mode == "160000" or object_type == "commit":
        raise PreparationError(f"Review inputs with submodules are not supported: {path}")
    if mode not in ("100644", "100755") or object_type != "blob":
        raise PreparationError(
            f"Review inputs support only regular Git blobs: {path} "
            f"(mode={mode}, type={object_type})"
        )
    if not OBJECT_ID_RE.fullmatch(object_id):
        raise PreparationError(f"Git returned an invalid object ID for {path}")
    try:
        size = int(size_raw)
    except ValueError as exc:
        raise PreparationError(f"Git returned an invalid blob size for {path}") from exc
    if size < 0:
        raise PreparationError(f"Git returned a negative blob size for {path}")
    return TreeEntry(mode=mode, object_id=object_id, size=size, path=path)


def tree_record_path(record: bytes) -> str:
    try:
        metadata, raw_path = record.split(b"\t", 1)
        mode_raw, type_raw, object_id_raw, _ = metadata.split(b" ", 3)
        mode_raw.decode("ascii", "strict")
        type_raw.decode("ascii", "strict")
        object_id = object_id_raw.decode("ascii", "strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PreparationError("Git returned malformed tree metadata") from exc
    if not OBJECT_ID_RE.fullmatch(object_id):
        raise PreparationError("Git returned an invalid tree object ID")
    return safe_path(raw_path)


def scan_tree(
    repo: Path,
    sha: str,
    *,
    label: str,
    collect: bool,
    scope: ReviewScope | None = None,
    max_entries: int | None = None,
    max_bytes: int | None = None,
) -> tuple[list[TreeEntry], int, int]:
    """Stream one exact tree, validating modes and optional materialization bounds."""

    command = git_command(repo, "ls-tree", "-r", "-z", "-l", "--full-tree", sha)
    entries: list[TreeEntry] = []
    entry_count = 0
    total_bytes = 0
    file_keys: dict[tuple[str, ...], str] = {}
    directory_keys: dict[tuple[str, ...], str] = {}
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=git_env(),
        )
        assert process.stdout is not None
        pending = bytearray()
        try:
            while True:
                chunk = process.stdout.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                pending.extend(chunk)
                while True:
                    terminator = pending.find(0)
                    if terminator < 0:
                        if len(pending) > MAX_TREE_RECORD_BYTES:
                            raise PreparationError(
                                f"{label} tree contains an overlong Git record"
                            )
                        break
                    record = bytes(pending[:terminator])
                    del pending[: terminator + 1]
                    if not record:
                        raise PreparationError(f"{label} tree contains an empty Git record")
                    path = tree_record_path(record)
                    if scope is not None and not scope.allows_read(path):
                        continue
                    entry = parse_tree_record(record)
                    entry_count += 1
                    total_bytes += entry.size
                    if max_entries is not None and entry_count > max_entries:
                        raise PreparationError(
                            f"{label} tree has more than {max_entries} entries; "
                            "refusing to materialize it"
                        )
                    if max_bytes is not None and total_bytes > max_bytes:
                        raise PreparationError(
                            f"{label} tree exceeds the configured {max_bytes}-byte "
                            "materialization limit"
                        )
                    if collect:
                        key = portable_path_key(entry.path)
                        raw_parts = PurePosixPath(entry.path).parts
                        prior = file_keys.get(key)
                        if prior is not None:
                            raise PreparationError(
                                "Head tree contains paths that collide on a portable "
                                f"filesystem: {prior!r} and {entry.path!r}"
                            )
                        prior_descendant = directory_keys.get(key)
                        if prior_descendant is not None:
                            raise PreparationError(
                                "Head tree contains a file/directory path collision: "
                                f"{entry.path!r} and {prior_descendant!r}"
                            )
                        for length in range(1, len(key)):
                            prefix = key[:length]
                            raw_prefix = "/".join(raw_parts[:length])
                            prior_file = file_keys.get(prefix)
                            if prior_file is not None:
                                raise PreparationError(
                                    "Head tree contains a file/directory path collision: "
                                    f"{prior_file!r} and {entry.path!r}"
                                )
                            prior_directory = directory_keys.get(prefix)
                            if (
                                prior_directory is not None
                                and prior_directory != raw_prefix
                            ):
                                raise PreparationError(
                                    "Head tree contains directory paths that collide "
                                    "on a portable filesystem: "
                                    f"{prior_directory!r} and {raw_prefix!r}"
                                )
                            directory_keys[prefix] = raw_prefix
                        file_keys[key] = entry.path
                        entries.append(entry)
            if pending:
                raise PreparationError(f"{label} tree ended with a malformed Git record")
            returncode = process.wait()
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        if returncode != 0:
            raise PreparationError(git_error(command, stderr))
    return entries, entry_count, total_bytes


def reject_special_tree_entries(
    repo: Path,
    sha: str,
    label: str,
    scope: ReviewScope | None = None,
) -> None:
    scan_tree(repo, sha, label=label, collect=False, scope=scope)


def parse_name_status(raw: bytes) -> list[dict[str, Any]]:
    tokens = raw.split(b"\0")
    files: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index].decode("ascii", "strict")
        index += 1
        if not STATUS_RE.fullmatch(status):
            raise PreparationError(f"Unsupported Git change status: {status}")
        if status.startswith(("R", "C")):
            if index + 1 >= len(tokens):
                raise PreparationError("Malformed rename/copy record from git diff")
            old_path = safe_path(tokens[index])
            path = safe_path(tokens[index + 1])
            index += 2
        else:
            if index >= len(tokens):
                raise PreparationError("Malformed path record from git diff")
            old_path = None
            path = safe_path(tokens[index])
            index += 1
        files.append({"path": path, "old_path": old_path, "status": status})
    return files


def parse_numstat(raw: bytes) -> dict[tuple[str | None, str], tuple[int | None, int | None]]:
    tokens = raw.split(b"\0")
    counts: dict[tuple[str | None, str], tuple[int | None, int | None]] = {}
    index = 0
    while index < len(tokens) and tokens[index]:
        fields = tokens[index].split(b"\t", 2)
        index += 1
        if len(fields) != 3:
            raise PreparationError("Malformed numstat record from git diff")
        additions = None if fields[0] == b"-" else int(fields[0])
        deletions = None if fields[1] == b"-" else int(fields[1])
        if fields[2]:
            old_path = None
            path = safe_path(fields[2])
        else:
            if index + 1 >= len(tokens):
                raise PreparationError("Malformed rename/copy numstat record")
            old_path = safe_path(tokens[index])
            path = safe_path(tokens[index + 1])
            index += 2
        counts[(old_path, path)] = (additions, deletions)
    return counts


def make_patch(
    repo: Path,
    base: str,
    head: str,
    entry: dict[str, Any],
    *,
    maximum: int,
) -> str:
    paths = [entry["path"]]
    if entry["old_path"] and entry["old_path"] != entry["path"]:
        paths.insert(0, entry["old_path"])
    raw = bounded_git_output(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--find-renames=50%",
        "--unified=80",
        base,
        head,
        "--",
        *paths,
        maximum=maximum,
        label=f"Patch for {entry['path']!r}",
        attr_source=head,
    )
    try:
        return raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise PreparationError(
            f"Patch for {entry['path']} is not UTF-8; mark the file binary or review it separately"
        ) from exc


def read_exactly(stream: Any, length: int, destination: Any, label: str) -> None:
    remaining = length
    while remaining:
        chunk = stream.read(min(STREAM_CHUNK_BYTES, remaining))
        if not chunk:
            raise PreparationError(f"Git ended while streaming {label}")
        destination.write(chunk)
        remaining -= len(chunk)


def prepare_checkout(
    source: Path,
    checkout: Path,
    head: str,
    entries: list[TreeEntry],
) -> None:
    """Materialize validated exact blobs without fetching history or running filters."""

    checkout.mkdir(parents=True, mode=0o700)
    command = git_command(source, "cat-file", "--batch")
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=git_env(),
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            for entry in entries:
                process.stdin.write(f"{entry.object_id}\n".encode("ascii"))
                process.stdin.flush()
                header = process.stdout.readline(256)
                if not header.endswith(b"\n") or len(header) >= 256:
                    raise PreparationError(
                        f"Git returned malformed batch metadata for {entry.path}"
                    )
                try:
                    object_id_raw, object_type, size_raw = header.rstrip(b"\n").split(b" ")
                    object_id = object_id_raw.decode("ascii", "strict")
                    size = int(size_raw)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise PreparationError(
                        f"Git returned malformed batch metadata for {entry.path}"
                    ) from exc
                if (
                    object_id != entry.object_id
                    or object_type != b"blob"
                    or size != entry.size
                ):
                    raise PreparationError(
                        f"Git object metadata changed while reading {entry.path}"
                    )

                destination = checkout.joinpath(*PurePosixPath(entry.path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(destination, flags, 0o600)
                try:
                    with os.fdopen(descriptor, "wb", closefd=False) as output:
                        read_exactly(process.stdout, entry.size, output, entry.path)
                        output.flush()
                    if process.stdout.read(1) != b"\n":
                        raise PreparationError(
                            f"Git returned malformed blob framing for {entry.path}"
                        )
                    os.fchmod(descriptor, 0o700 if entry.mode == "100755" else 0o600)
                finally:
                    os.close(descriptor)
            process.stdin.close()
            returncode = process.wait()
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        if returncode != 0:
            raise PreparationError(git_error(command, stderr))

    # The model-facing plugin needs only a detached exact-head marker. It gets
    # no object history, refs, config, remotes, credentials, or Git filters.
    metadata = checkout / ".git"
    metadata.mkdir(mode=0o700)
    marker = metadata / "HEAD"
    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    try:
        os.write(descriptor, f"{head}\n".encode("ascii"))
        os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)
    metadata.chmod(0o500)


def exact_tree_entry(
    repo: Path,
    sha: str,
    path: str,
) -> tuple[bytes, bytes, str] | None:
    listing = git(
        repo,
        "ls-tree",
        "-z",
        "--full-tree",
        sha,
        "--",
        path,
    )
    assert isinstance(listing, bytes)
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1:
        raise PreparationError("Git returned an ambiguous exact tree selector")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
    except ValueError as exc:
        raise PreparationError("Git returned malformed exact tree metadata") from exc
    if safe_path(raw_path) != path:
        raise PreparationError("Git returned an unexpected exact tree path")
    try:
        oid = object_id.decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise PreparationError("Git returned a non-ASCII object ID") from exc
    if not OBJECT_ID_RE.fullmatch(oid):
        raise PreparationError("Git returned an invalid exact tree object ID")
    return mode, object_type, oid


def read_profile_blob(
    repo: Path,
    object_id: str,
) -> bytes:
    size_text = str(git(repo, "cat-file", "-s", object_id, text=True)).strip()
    try:
        size = int(size_text)
    except ValueError as exc:
        raise PreparationError("Trusted base profile has an invalid Git object size") from exc
    if size > MAX_PROFILE_BYTES:
        raise PreparationError("Profile exceeds the 1 MiB limit")
    data = bounded_git_output(
        repo,
        "cat-file",
        "blob",
        object_id,
        maximum=size,
        label="Trusted base profile",
    )
    if len(data) != size:
        raise PreparationError("Trusted base profile size changed while it was read")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise PreparationError("Profile must be UTF-8") from exc
    return data


def profile_for_review(
    repo: Path,
    base: str,
    head: str,
    profile_path: str,
    bootstrap_profile_oid: str | None,
) -> tuple[bytes, str, str, str, str]:
    base_entry = exact_tree_entry(repo, base, profile_path)
    if bootstrap_profile_oid is None:
        if base_entry is None:
            raise PreparationError(
                f"Trusted base {base} must contain exactly one {profile_path} blob"
            )
        mode, object_type, object_id = base_entry
        if mode != b"100644" or object_type != b"blob":
            raise PreparationError(
                f"Trusted base profile must be a non-executable regular blob: {profile_path}"
            )
        data = read_profile_blob(repo, object_id)
        profile_origin = "target_base"
        exposed_object_id = object_id
    else:
        if base_entry is not None:
            raise PreparationError(
                "--bootstrap-profile-oid is allowed only when the trusted base "
                "does not contain --profile-path"
            )
        if not OBJECT_ID_RE.fullmatch(bootstrap_profile_oid):
            raise PreparationError(
                "--bootstrap-profile-oid must be a full lowercase Git object ID"
            )
        head_entry = exact_tree_entry(repo, head, profile_path)
        if head_entry is None:
            raise PreparationError(
                "Bootstrap profile must exist at --profile-path in the exact head"
            )
        mode, object_type, object_id = head_entry
        if (
            mode != b"100644"
            or object_type != b"blob"
            or object_id != bootstrap_profile_oid
        ):
            raise PreparationError(
                "Bootstrap profile OID does not match the exact non-executable "
                "head profile blob"
            )
        data = read_profile_blob(repo, object_id)
        profile_origin = "operator_bootstrap"
        exposed_object_id = object_id

    text = data.decode("utf-8", "strict")
    matches = list(PROFILE_SOURCE_RE.finditer(text))
    if len(matches) != 1:
        raise PreparationError(
            "Trusted base profile must contain exactly one canonical metadata.source_commit"
        )
    source_commit = full_sha(matches[0].group(1), "profile metadata.source_commit")
    require_commit(repo, source_commit, "profile source")
    if profile_origin == "operator_bootstrap" and source_commit != base:
        raise PreparationError(
            "Bootstrap profile metadata.source_commit must equal the target base_sha"
        )
    if profile_origin == "target_base" and not is_ancestor(repo, source_commit, base):
        raise PreparationError(
            "Profile metadata.source_commit must be an ancestor of the target base_sha"
        )
    return (
        data,
        hashlib.sha256(data).hexdigest(),
        source_commit,
        profile_origin,
        exposed_object_id,
    )


def validate_scope_selectors(
    repo: Path,
    base: str,
    head: str,
    scope: ReviewScope,
) -> None:
    """Require scoped selectors to resolve exactly in the trusted base tree."""

    if scope.mode == "repository":
        return
    support_set = set(scope.support_paths)
    for path in (*scope.roots, *scope.support_paths):
        base_entry = exact_tree_entry(repo, base, path)
        head_entry = exact_tree_entry(repo, head, path)
        if path in support_set:
            valid = (
                base_entry is not None
                and head_entry is not None
                and base_entry == head_entry
                and (
                    (
                        base_entry[0] in (b"100644", b"100755")
                        and base_entry[1] == b"blob"
                    )
                    or (
                        base_entry[0] == b"040000"
                        and base_entry[1] == b"tree"
                    )
                )
            )
        else:
            entries = [entry for entry in (base_entry, head_entry) if entry is not None]
            valid = bool(entries) and all(
                (
                    mode in (b"100644", b"100755") and object_type == b"blob"
                ) or (mode == b"040000" and object_type == b"tree")
                for mode, object_type, _ in entries
            )
        if not valid:
            raise PreparationError(
                "Configured review scope must select a regular file or directory "
                "in the trusted base or exact head; support paths must be unchanged "
                "regular files or directories in both trees"
            )


def add_tree(archive: tarfile.TarFile, root: Path) -> None:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
        ):
            raise PreparationError(f"Payload contains unsupported file type: {relative}")
        tar_info = archive.gettarinfo(str(path), arcname=str(relative))
        tar_info.uid = 0
        tar_info.gid = 0
        tar_info.uname = ""
        tar_info.gname = ""
        if path.is_dir():
            archive.addfile(tar_info)
        else:
            with path.open("rb") as stream:
                archive.addfile(tar_info, stream)


def encode_context(context: dict[str, Any]) -> bytes:
    return (
        json.dumps(context, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def encoded_object_size(value: dict[str, Any]) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--repository")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--event", type=Path)
    parser.add_argument("--acceptance-context", type=Path)
    parser.add_argument("--profile-path", default=DEFAULT_PROFILE_REPO_PATH)
    parser.add_argument("--bootstrap-profile-oid")
    parser.add_argument("--scope-root", action="append", default=[])
    parser.add_argument("--support-path", action="append", default=[])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=10_000)
    parser.add_argument("--max-context-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument(
        "--max-checkout-files",
        type=int,
        default=DEFAULT_MAX_CHECKOUT_FILES,
    )
    parser.add_argument(
        "--max-checkout-bytes",
        type=int,
        default=DEFAULT_MAX_CHECKOUT_BYTES,
    )
    args = parser.parse_args()
    try:
        profile_path = safe_path(args.profile_path.encode("utf-8", "strict"))
    except (UnicodeEncodeError, PreparationError) as exc:
        raise PreparationError("--profile-path must be a canonical repository path") from exc
    bootstrap_profile_oid = (
        None
        if args.bootstrap_profile_oid is None
        else args.bootstrap_profile_oid.strip()
    )
    review_scope = review_scope_from_args(args.scope_root, args.support_path)
    scope_digest = hashlib.sha256(canonical_scope_bytes(review_scope)).hexdigest()

    if args.max_files < 1 or args.max_files > 10_000:
        raise PreparationError("--max-files must be between 1 and 10000")
    if args.max_context_bytes < 1024 or args.max_context_bytes > 32 * 1024 * 1024:
        raise PreparationError("--max-context-bytes must be between 1024 and 33554432")
    if args.max_checkout_files < 1 or args.max_checkout_files > MAX_CHECKOUT_FILES:
        raise PreparationError(
            f"--max-checkout-files must be between 1 and {MAX_CHECKOUT_FILES}"
        )
    if args.max_checkout_bytes < 1 or args.max_checkout_bytes > MAX_CHECKOUT_BYTES:
        raise PreparationError(
            f"--max-checkout-bytes must be between 1 and {MAX_CHECKOUT_BYTES}"
        )

    root_text = str(git(args.repo, "rev-parse", "--show-toplevel", text=True)).strip()
    root = Path(root_text).resolve(strict=True)
    validate_exact_graph_source(root)

    if args.event:
        # Preserve the final path component for load_event's lstat check.
        # Path.resolve() would follow a caller-supplied symlink before the
        # function could reject it.
        event = load_event(args.event.absolute())
        base, head, repository, pr_number = event_values(event)
        if args.base and full_sha(args.base, "--base") != base:
            raise PreparationError("--base does not match the event payload")
        if args.head and full_sha(args.head, "--head") != head:
            raise PreparationError("--head does not match the event payload")
        if args.repository and args.repository != repository:
            raise PreparationError("--repository does not match the event payload")
        if args.pr_number and args.pr_number != pr_number:
            raise PreparationError("--pr-number does not match the event payload")
    else:
        if not args.base or not args.head:
            raise PreparationError("Provide --event or both --base and --head")
        base = full_sha(args.base, "--base")
        head = full_sha(args.head, "--head")
        pr_number = args.pr_number
        repository = args.repository
        if not repository:
            remote = str(git(root, "remote", "get-url", "origin", text=True)).strip()
            repository = canonical_repository_from_url(remote)
        if not repository or not REPOSITORY_RE.fullmatch(repository):
            raise PreparationError(
                "Could not derive owner/repo from a GitHub origin; provide --repository"
            )

    require_commit(root, base, "base")
    require_commit(root, head, "head")
    merge_base = unique_merge_base(root, base, head)
    require_commit(root, merge_base, "merge base")
    validate_scope_selectors(root, base, head, review_scope)
    head_entries, checkout_files, checkout_bytes = scan_tree(
        root,
        head,
        label="Head",
        collect=True,
        scope=review_scope,
        max_entries=args.max_checkout_files,
        max_bytes=args.max_checkout_bytes,
    )
    reject_special_tree_entries(root, base, "Base", review_scope)
    if merge_base != base:
        reject_special_tree_entries(root, merge_base, "Merge-base", review_scope)

    acceptance_context = None
    acceptance_context_digest = None
    if args.acceptance_context:
        acceptance_context, acceptance_context_digest = load_acceptance_context(
            args.acceptance_context.absolute(),
            repository=repository,
            pull_request_number=pr_number,
            base_sha=base,
            head_sha=head,
        )

    (
        profile_data,
        profile_digest,
        profile_source_commit,
        profile_origin,
        profile_object_id,
    ) = profile_for_review(
        root,
        base,
        head,
        profile_path,
        bootstrap_profile_oid,
    )
    validate_exact_attribute_source(root, head, profile_path)
    name_status = bounded_git_output(
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames=50%",
        f"{merge_base}..{head}",
        "--",
        maximum=args.max_context_bytes,
        label="Changed-file inventory",
        attr_source=head,
    )
    files = parse_name_status(name_status)
    del name_status
    if any(
        not review_scope.allows_change(path)
        for entry in files
        for path in (entry["path"], entry["old_path"])
        if path is not None
    ):
        raise PreparationError(
            "Changed-file inventory is outside the configured review scope"
        )
    if len(files) > args.max_files:
        raise PreparationError(
            f"Change has {len(files)} files; configured fail-closed limit is {args.max_files}"
        )
    numstat = bounded_git_output(
        root,
        "diff",
        "--numstat",
        "-z",
        "--find-renames=50%",
        f"{merge_base}..{head}",
        "--",
        maximum=args.max_context_bytes,
        label="Changed-line inventory",
        attr_source=head,
    )
    counts = parse_numstat(numstat)
    del numstat
    for entry in files:
        entry["additions"], entry["deletions"] = counts.get(
            (entry["old_path"], entry["path"]), (None, None)
        )
        entry["patch"] = ""
        entry["patch_truncated"] = False
        entry["patch_original_bytes"] = 0
        entry["patch_original_lines"] = 0
    del counts

    context = {
        "version": 1,
        "repository": repository,
        "base_sha": base,
        "merge_base_sha": merge_base,
        "head_sha": head,
        "profile_digest": profile_digest,
        "profile_source_commit": profile_source_commit,
        "profile_path": profile_path,
        "profile_origin": profile_origin,
        "profile_object_id": profile_object_id,
        "review_scope": review_scope.as_json(),
        "scope_digest": scope_digest,
        "pull_request_number": pr_number,
        "acceptance_context_digest": acceptance_context_digest,
        "acceptance_context": acceptance_context,
        "files": files,
    }
    encoded = encode_context(context)
    context_bytes = len(encoded)
    if context_bytes > args.max_context_bytes:
        raise PreparationError(
            f"Context metadata is {context_bytes} bytes; configured fail-closed limit is "
            f"{args.max_context_bytes}"
        )

    # Each diff is captured with only the aggregate context budget remaining.
    # The candidate entry is serialized and checked before it is retained.
    for entry in files:
        old_size = encoded_object_size(entry)
        remaining = args.max_context_bytes - context_bytes
        patch = make_patch(
            root,
            merge_base,
            head,
            entry,
            maximum=remaining,
        )
        candidate = dict(entry)
        candidate["patch"] = patch
        candidate["patch_original_bytes"] = len(patch.encode("utf-8"))
        candidate["patch_original_lines"] = len(patch.splitlines())
        candidate_size = encoded_object_size(candidate)
        candidate_context_bytes = context_bytes + candidate_size - old_size
        if candidate_context_bytes > args.max_context_bytes:
            raise PreparationError(
                f"Patch for {entry['path']!r} would make the complete context "
                f"{candidate_context_bytes} bytes; configured fail-closed limit is "
                f"{args.max_context_bytes}"
            )
        entry.update(candidate)
        context_bytes = candidate_context_bytes

    encoded = encode_context(context)
    if len(encoded) != context_bytes or len(encoded) > args.max_context_bytes:
        raise PreparationError("Internal context budget accounting did not reconcile")

    # No payload path is created until all exact-tree and diff budgets pass.
    args.output.mkdir(parents=True, exist_ok=False)
    payload = args.output / "payload"
    checkout = payload / "repo"
    payload.mkdir(mode=0o700)
    prepare_checkout(root, checkout, head, head_entries)
    (payload / "profile.yaml").write_bytes(profile_data)
    context_path = payload / "context.json"
    context_path.write_bytes(encoded)

    attestation_key = payload / "attestation.key"
    attestation_key.write_bytes(os.urandom(32))
    attestation_key.chmod(0o400)

    archive_path = args.output / "review-input.tar.gz"
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
        add_tree(archive, payload)

    print(
        json.dumps(
            {
                "repository": repository,
                "base_sha": base,
                "merge_base_sha": merge_base,
                "head_sha": head,
                "pull_request_number": pr_number,
                "profile_digest": profile_digest,
                "profile_source_commit": profile_source_commit,
                "profile_path": profile_path,
                "profile_origin": profile_origin,
                "profile_object_id": profile_object_id,
                "review_scope": review_scope.as_json(),
                "scope_digest": scope_digest,
                "acceptance_context_digest": acceptance_context_digest,
                "acceptance_issue_count": (
                    0
                    if acceptance_context is None
                    else len(acceptance_context["closing_issues"])
                ),
                "context_digest": hashlib.sha256(encoded).hexdigest(),
                "changed_files": len(files),
                "checkout_files": checkout_files,
                "checkout_bytes": checkout_bytes,
                "context_bytes": len(encoded),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreparationError, OSError, subprocess.SubprocessError) as error:
        print(f"prepare-review: {error}", file=sys.stderr)
        raise SystemExit(1)
