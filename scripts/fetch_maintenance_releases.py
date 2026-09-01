#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fetch the latest stable upstream releases used by catalog maintenance checks."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from scripts.catalog_maintenance_policy import (
        MaintenancePolicy,
        MaintenancePolicyError,
        load_maintenance_policy_file,
    )
    from scripts.example_dependencies import (
        DependencyContractError,
        load_dependency_contract,
    )
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from catalog_maintenance_policy import (  # type: ignore[no-redef]
        MaintenancePolicy,
        MaintenancePolicyError,
        load_maintenance_policy_file,
    )
    from example_dependencies import (  # type: ignore[no-redef]
        DependencyContractError,
        load_dependency_contract,
    )


GITHUB_API_ROOT = "https://api.github.com"
DEFAULT_POLICY_PATH = Path("scripts/catalog-maintenance.json")
DEFAULT_OUTPUT_PATH = Path("scripts/catalog-maintenance-releases.json")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
STABLE_VERSION_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")

JsonGetter = Callable[[str, str | None], Any]


class MaintenanceFetchError(ValueError):
    """Raised when maintenance policy or upstream data cannot be trusted."""


def find_repo_root() -> Path:
    """Find the nearest repository root, falling back to the working directory."""

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
    return current


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaintenanceFetchError(f"{context} must be a JSON object.")
    return value


def load_policy(path: Path) -> MaintenancePolicy:
    """Load and validate the maintenance policy consumed by this fetcher."""

    try:
        return load_maintenance_policy_file(path)
    except MaintenancePolicyError as error:
        raise MaintenanceFetchError(str(error)) from error


def github_json(url: str, token: str | None = None) -> Any:
    """Fetch and decode one response from the public GitHub REST API."""

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nemoclaw-community-maintenance/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > MAX_RESPONSE_BYTES:
                raise MaintenanceFetchError(
                    f"GitHub API response is larger than {MAX_RESPONSE_BYTES} bytes: {url}"
                )
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except MaintenanceFetchError:
        raise
    except HTTPError as error:
        raise MaintenanceFetchError(
            f"GitHub API request failed with HTTP {error.code}: {url}"
        ) from error
    except (OSError, URLError) as error:
        raise MaintenanceFetchError(f"GitHub API request failed: {url}: {error}") from error
    except ValueError as error:
        raise MaintenanceFetchError(
            f"GitHub API returned an invalid Content-Length: {url}"
        ) from error

    if len(content) > MAX_RESPONSE_BYTES:
        raise MaintenanceFetchError(
            f"GitHub API response is larger than {MAX_RESPONSE_BYTES} bytes: {url}"
        )
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MaintenanceFetchError(
            f"GitHub API returned invalid JSON: {url}"
        ) from error


def parse_github_timestamp(value: Any, context: str) -> datetime:
    """Parse a timezone-aware GitHub timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value.strip():
        raise MaintenanceFetchError(f"{context} is missing a published timestamp.")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise MaintenanceFetchError(
            f"{context} has an invalid published timestamp."
        ) from error
    if parsed.tzinfo is None:
        raise MaintenanceFetchError(
            f"{context} published timestamp must include a timezone."
        )
    return parsed.astimezone(timezone.utc)


def normalize_checked_at(value: str | None = None) -> str:
    """Return the snapshot timestamp as second-precision UTC ISO 8601."""

    if value is None:
        checked_at = datetime.now(timezone.utc)
    else:
        checked_at = parse_github_timestamp(value, "--checked-at")
    return checked_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _release_url(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}"


def fetch_latest_release(
    repository: str,
    token: str | None,
    get_json: JsonGetter,
) -> dict[str, str]:
    """Return the most recently published non-draft, non-prerelease release."""

    # GitHub's `latest` endpoint excludes drafts and prereleases server-side. It
    # also avoids downloading large release bodies for an entire release list.
    url = f"{GITHUB_API_ROOT}/repos/{repository}/releases/latest"
    payload = get_json(url, token)
    if not isinstance(payload, dict):
        raise MaintenanceFetchError(
            f"GitHub latest release response for {repository} must be a JSON object."
        )
    if payload.get("draft") or payload.get("prerelease"):
        raise MaintenanceFetchError(
            f"GitHub did not return a published stable release for {repository}."
        )
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise MaintenanceFetchError(
            f"Latest stable release for {repository} is missing a tag."
        )
    published_at = parse_github_timestamp(
        payload.get("published_at"), f"Release {tag!r} in {repository}"
    )
    release_url = payload.get("html_url")
    if not isinstance(release_url, str) or not release_url.startswith("https://"):
        release_url = _release_url(repository, tag)
    return {
        "tag": tag,
        "published_on": published_at.date().isoformat(),
        "url": release_url,
    }


def fetch_tag_commit(
    repository: str,
    tag: str,
    token: str | None,
    get_json: JsonGetter,
) -> tuple[str, datetime]:
    """Resolve a tag to its commit and best authoritative publication time."""

    encoded_tag = quote(tag, safe="")
    ref = _require_object(
        get_json(
            f"{GITHUB_API_ROOT}/repos/{repository}/git/ref/tags/{encoded_tag}",
            token,
        ),
        f"GitHub tag ref response for {repository}",
    )
    target = _require_object(
        ref.get("object"), f"GitHub tag ref target for {repository}"
    )
    target_type = target.get("type")
    target_sha = target.get("sha")
    if (
        target_type not in {"commit", "tag"}
        or not isinstance(target_sha, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", target_sha) is None
    ):
        raise MaintenanceFetchError(f"Tag {tag!r} in {repository} has an invalid target.")

    published_at: datetime | None = None
    if target_type == "tag":
        tag_object = _require_object(
            get_json(
                f"{GITHUB_API_ROOT}/repos/{repository}/git/tags/{target_sha}", token
            ),
            f"GitHub annotated tag response for {repository}",
        )
        tagger = _require_object(
            tag_object.get("tagger"), f"GitHub annotated tagger for {repository}"
        )
        published_at = parse_github_timestamp(
            tagger.get("date"), f"Annotated tag {tag!r} in {repository}"
        )
        target = _require_object(
            tag_object.get("object"), f"GitHub annotated tag target for {repository}"
        )
        target_sha = target.get("sha")
        if target.get("type") != "commit" or not isinstance(
            target_sha, str
        ) or re.fullmatch(r"[0-9a-fA-F]{40}", target_sha) is None:
            raise MaintenanceFetchError(
                f"Annotated tag {tag!r} in {repository} must target one commit."
            )
        return target_sha.casefold(), published_at

    commit_payload = _require_object(
        get_json(
            f"{GITHUB_API_ROOT}/repos/{repository}/commits/{target_sha}", token
        ),
        f"GitHub tag commit response for {repository}",
    )
    commit_sha = commit_payload.get("sha")
    if commit_sha != target_sha:
        raise MaintenanceFetchError(
            f"Tag {tag!r} in {repository} resolved to an unexpected commit."
        )
    commit_details = _require_object(
        commit_payload.get("commit"), f"GitHub commit details for {repository}"
    )
    committer = commit_details.get("committer")
    author = commit_details.get("author")
    timestamp: Any = None
    if isinstance(committer, dict):
        timestamp = committer.get("date")
    if timestamp is None and isinstance(author, dict):
        timestamp = author.get("date")
    commit_time = parse_github_timestamp(timestamp, f"Tag {tag!r} in {repository}")
    return target_sha.casefold(), published_at or commit_time


def fetch_tag_channel(
    repository: str,
    channel: str,
    token: str | None,
    get_json: JsonGetter,
) -> tuple[dict[str, str], str]:
    """Resolve a maintained tag channel to its exact stable version tag."""

    target_sha, _channel_commit_time = fetch_tag_commit(
        repository, channel, token, get_json
    )

    tags_url = f"{GITHUB_API_ROOT}/repos/{repository}/tags?per_page=100"
    tags = get_json(tags_url, token)
    if not isinstance(tags, list):
        raise MaintenanceFetchError(
            f"GitHub tags response for {repository} must be a JSON array."
        )
    candidates: list[str] = []
    for item in tags:
        if not isinstance(item, dict):
            continue
        tag = item.get("name")
        commit = item.get("commit")
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        if (
            isinstance(tag, str)
            and STABLE_VERSION_TAG_RE.fullmatch(tag)
            and commit_sha == target_sha
        ):
            candidates.append(tag)
    if not candidates:
        raise MaintenanceFetchError(
            f"Tag channel {channel!r} in {repository} does not resolve to an exact "
            "stable vX.Y.Z tag in the latest 100 tags."
        )
    selected_tag = max(
        candidates,
        key=lambda value: tuple(int(part) for part in value[1:].split(".")),
    )
    selected_sha, published_at = fetch_tag_commit(
        repository, selected_tag, token, get_json
    )
    if selected_sha != target_sha:
        raise MaintenanceFetchError(
            f"Stable tag {selected_tag!r} moved while resolving channel {channel!r}."
        )

    return (
        {
            "tag": selected_tag,
            "published_on": published_at.date().isoformat(),
            "url": f"https://github.com/{repository}/tree/{quote(selected_tag, safe='')}",
        },
        selected_sha,
    )


def fetch_repository_file(
    repository: str,
    revision: str,
    path: str,
    token: str | None,
    get_json: JsonGetter,
) -> str:
    """Fetch one UTF-8 repository file through the authenticated GitHub API."""

    encoded_path = quote(path, safe="/")
    encoded_revision = quote(revision, safe="")
    url = (
        f"{GITHUB_API_ROOT}/repos/{repository}/contents/{encoded_path}"
        f"?ref={encoded_revision}"
    )
    payload = _require_object(
        get_json(url, token), f"GitHub contents response for {repository}/{path}"
    )
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise MaintenanceFetchError(
            f"GitHub contents response for {repository}/{path} is not base64 data."
        )
    try:
        encoded = "".join(payload["content"].split())
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise MaintenanceFetchError(
            f"GitHub contents response for {repository}/{path} is invalid."
        ) from error


def _required_match(pattern: str, source: str, context: str) -> str:
    matches = re.findall(pattern, source, flags=re.MULTILINE)
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise MaintenanceFetchError(f"Unable to resolve exactly one {context}.")
    return matches[0]


def fetch_nemoclaw_stack(
    tag: str,
    token: str | None,
    get_json: JsonGetter,
    commit: str | None = None,
) -> dict[str, Any]:
    """Resolve a NemoClaw tag to its authoritative agent/runtime contract."""

    repository = "NVIDIA/NemoClaw"
    commit = commit or fetch_tag_commit(repository, tag, token, get_json)[0]
    blueprint = fetch_repository_file(
        repository,
        commit,
        "nemoclaw-blueprint/blueprint.yaml",
        token,
        get_json,
    )
    minimum = _required_match(
        r'^min_openshell_version:\s*["\']([0-9]+(?:\.[0-9]+){2})["\']\s*$',
        blueprint,
        f"OpenShell minimum for NemoClaw {tag}",
    )
    maximum = _required_match(
        r'^max_openshell_version:\s*["\']([0-9]+(?:\.[0-9]+){2})["\']\s*$',
        blueprint,
        f"OpenShell maximum for NemoClaw {tag}",
    )
    if minimum != maximum:
        raise MaintenanceFetchError(
            f"NemoClaw {tag} supports OpenShell {minimum} through {maximum}; "
            "the catalog cannot truthfully publish one exact runtime version."
        )
    harnesses: dict[str, str] = {}
    for agent in ("hermes", "openclaw"):
        manifest = fetch_repository_file(
            repository,
            commit,
            f"agents/{agent}/manifest.yaml",
            token,
            get_json,
        )
        version = _required_match(
            r'^expected_version:\s*["\']?([0-9]+(?:\.[0-9]+){2})["\']?\s*$',
            manifest,
            f"{agent} version for NemoClaw {tag}",
        )
        harnesses[agent] = version
    return {
        "commit": commit,
        "harnesses": harnesses,
        "openshell": minimum,
    }


def validate_previous_nemoclaw_stacks(value: dict[str, Any]) -> dict[str, Any]:
    """Validate retained immutable tag resolutions before carrying them forward."""

    for tag, raw_record in value.items():
        if not isinstance(tag, str) or STABLE_VERSION_TAG_RE.fullmatch(tag) is None:
            raise MaintenanceFetchError(f"Invalid NemoClaw stack tag {tag!r}.")
        record = _require_object(raw_record, f"NemoClaw stack {tag}")
        commit = record.get("commit")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise MaintenanceFetchError(f"NemoClaw stack {tag} has an invalid commit.")
        openshell = record.get("openshell")
        if not isinstance(openshell, str) or re.fullmatch(
            r"\d+(?:\.\d+){2}", openshell
        ) is None:
            raise MaintenanceFetchError(
                f"NemoClaw stack {tag} has an invalid OpenShell version."
            )
        harnesses = _require_object(
            record.get("harnesses"), f"NemoClaw stack {tag} harnesses"
        )
        if set(harnesses) != {"hermes", "openclaw"}:
            raise MaintenanceFetchError(
                f"NemoClaw stack {tag} must define Hermes and OpenClaw."
            )
        for harness, version in harnesses.items():
            if not isinstance(version, str) or re.fullmatch(
                r"\d+(?:\.\d+){2}", version
            ) is None:
                raise MaintenanceFetchError(
                    f"NemoClaw stack {tag} has an invalid {harness} version."
                )
    return dict(value)


def discover_nemoclaw_versions(root: Path) -> set[str]:
    """Discover exact NemoClaw tags from executable example contracts."""

    versions: set[str] = set()
    patterns = (
        "examples/recipes/nvidia/*/dependencies.toml",
        "examples/recipes/community/*/dependencies.toml",
        "examples/recipes/partners/*/*/dependencies.toml",
        "examples/demos/field/*/dependencies.toml",
        "examples/tools/*/dependencies.toml",
    )
    paths = sorted({path for pattern in patterns for path in root.glob(pattern)})
    for path in paths:
        try:
            contract = load_dependency_contract(path)
        except DependencyContractError as error:
            raise MaintenanceFetchError(str(error)) from error
        if contract.distribution == "nemoclaw":
            assert contract.version is not None
            versions.add(contract.version)
    return versions


def fetch_component_version(
    dependency_id: str,
    repository: str,
    release: dict[str, str],
    token: str | None,
    get_json: JsonGetter,
) -> str:
    """Return the installed component version represented by an upstream release."""

    tag = release["tag"]
    if dependency_id != "hermes-agent":
        version = tag.removeprefix("v")
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) is None:
            raise MaintenanceFetchError(
                f"Release {tag!r} for {dependency_id} is not a numeric version."
            )
        return version
    project = fetch_repository_file(
        repository, tag, "pyproject.toml", token, get_json
    )
    return _required_match(
        r'^version\s*=\s*["\']([0-9]+(?:\.[0-9]+){2})["\']\s*$',
        project,
        f"Hermes Agent package version at {tag}",
    )


def build_snapshot(
    policy: MaintenancePolicy,
    checked_at: str,
    token: str | None = None,
    get_json: JsonGetter = github_json,
    root: Path | None = None,
    previous_stacks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch every registered dependency and return a stable snapshot object."""

    releases: dict[str, dict[str, str]] = {}
    nemoclaw_lkg_commit: str | None = None
    for dependency in policy.dependencies:
        dependency_id = dependency.id
        repository = dependency.repository
        source = dependency.source
        try:
            if source == "releases":
                release = fetch_latest_release(repository, token, get_json)
            elif source == "tag-channel":
                release, channel_commit = fetch_tag_channel(
                    repository, str(dependency.channel), token, get_json
                )
                if dependency_id == "nemoclaw":
                    nemoclaw_lkg_commit = channel_commit
            else:
                raise MaintenanceFetchError(
                    f"Unsupported maintenance source {source!r}."
                )
        except MaintenanceFetchError as error:
            raise MaintenanceFetchError(
                f"Unable to refresh {dependency_id} ({repository}): {error}"
            ) from error
        releases[dependency_id] = release
        releases[dependency_id]["component_version"] = fetch_component_version(
            dependency_id, repository, release, token, get_json
        )
    validated_previous = validate_previous_nemoclaw_stacks(previous_stacks or {})
    nemoclaw_stacks = {} if root is not None else dict(validated_previous)
    if root is not None:
        versions = discover_nemoclaw_versions(root)
        versions.add(releases["nemoclaw"]["tag"])
        for version in sorted(
            versions,
            key=lambda value: tuple(int(part) for part in value.removeprefix("v").split(".")),
        ):
            previous = validated_previous.get(version)
            if version == releases["nemoclaw"]["tag"]:
                if nemoclaw_lkg_commit is None:
                    raise MaintenanceFetchError(
                        "NemoClaw channel did not resolve an immutable commit."
                    )
                resolved_commit = nemoclaw_lkg_commit
            else:
                resolved_commit = fetch_tag_commit(
                    "NVIDIA/NemoClaw", version, token, get_json
                )[0]
            if (
                isinstance(previous, dict)
                and previous.get("commit") is not None
                and previous.get("commit") != resolved_commit
            ):
                raise MaintenanceFetchError(
                    f"NemoClaw tag {version} moved from {previous['commit']} to "
                    f"{resolved_commit}; refusing to rewrite an immutable contract."
                )
            if isinstance(previous, dict) and previous.get("commit") == resolved_commit:
                nemoclaw_stacks[version] = previous
            else:
                nemoclaw_stacks[version] = fetch_nemoclaw_stack(
                    version, token, get_json, commit=resolved_commit
                )
    return {
        "schema_version": 1,
        "checked_at": normalize_checked_at(checked_at),
        "releases": releases,
        "nemoclaw_stacks": nemoclaw_stacks,
    }


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Write a snapshot atomically with deterministic formatting."""

    if path.is_symlink():
        raise MaintenanceFetchError(f"Refusing to replace symlinked snapshot: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _root_relative_path(root: Path, value: Path | None, default: Path) -> Path:
    selected = default if value is None else value
    return selected if selected.is_absolute() else root / selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        help=f"Maintenance policy path (default: {DEFAULT_POLICY_PATH}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Release snapshot path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--checked-at",
        help="Override the UTC snapshot timestamp (useful for reproducible runs).",
    )
    args = parser.parse_args(argv)

    root = find_repo_root()
    policy_path = _root_relative_path(root, args.policy, DEFAULT_POLICY_PATH)
    output_path = _root_relative_path(root, args.output, DEFAULT_OUTPUT_PATH)
    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        policy = load_policy(policy_path)
        checked_at = normalize_checked_at(args.checked_at)
        previous_stacks: dict[str, Any] = {}
        checked_snapshot_path = root / DEFAULT_OUTPUT_PATH
        if checked_snapshot_path.is_file():
            try:
                checked_snapshot = json.loads(
                    checked_snapshot_path.read_text(encoding="utf-8")
                )
                if not isinstance(checked_snapshot, dict):
                    raise MaintenanceFetchError(
                        f"Existing stack snapshot {checked_snapshot_path} must be a JSON object."
                    )
                candidate_stacks = checked_snapshot.get("nemoclaw_stacks", {})
                if not isinstance(candidate_stacks, dict):
                    raise MaintenanceFetchError(
                        f"Existing stack snapshot {checked_snapshot_path} has invalid "
                        "nemoclaw_stacks."
                    )
                previous_stacks = candidate_stacks
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise MaintenanceFetchError(
                    f"Unable to read existing stack snapshot {checked_snapshot_path}: "
                    f"{error}"
                ) from error
        snapshot = build_snapshot(
            policy,
            checked_at,
            token=token,
            root=root,
            previous_stacks=previous_stacks,
        )
        write_snapshot(output_path, snapshot)
    except (MaintenanceFetchError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Maintenance releases refreshed for {len(snapshot['releases'])} dependencies: "
        f"{output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
