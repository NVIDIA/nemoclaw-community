#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fetch one bounded, exact-PR acceptance snapshot from the GitHub REST API.

This trusted-host helper deliberately does not request review comments, issue
comments, timelines, commits, or prior advisor output. It includes only the
current pull-request title/body and same-repository issues that the current PR
body names with an explicit GitHub closing keyword.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

API_ROOT = "https://api.github.com"
SCHEMA_VERSION = "review-advisor/pr-acceptance/v1"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
MAX_PR_TITLE_BYTES = 1024
MAX_PR_BODY_BYTES = 128 * 1024
MAX_CLOSING_ISSUES = 10
MAX_ISSUE_TITLE_BYTES = 1024
MAX_ISSUE_BODY_BYTES = 64 * 1024

_IDENTIFIER = r"[A-Za-z0-9_.-]+"
_CLOSING_REFERENCE_RE = re.compile(
    rf"""
    (?<![A-Za-z])
    (?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)
    \s*:?\s+
    (?:
      https://github[.]com/
        (?P<url_owner>{_IDENTIFIER})/
        (?P<url_repo>{_IDENTIFIER})/
        issues/(?P<url_number>[1-9][0-9]*)
      |
      (?:(?P<short_owner>{_IDENTIFIER})/(?P<short_repo>{_IDENTIFIER}))?
      [#](?P<short_number>[1-9][0-9]*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class FetchError(RuntimeError):
    """A bounded-input, identity, or GitHub API failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _full_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise FetchError(f"{label} must be a full lowercase 40-character commit SHA")
    return value


def _repository(value: Any, label: str = "repository") -> str:
    if not isinstance(value, str) or not REPOSITORY_RE.fullmatch(value):
        raise FetchError(f"{label} must use owner/name syntax")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 1 or value > 2_147_483_647:
        raise FetchError(f"{label} must be a positive integer")
    return value


def _bounded_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    empty: bool = True,
) -> str:
    if value is None and empty:
        value = ""
    if not isinstance(value, str):
        raise FetchError(f"{label} must be text")
    if not empty and not value.strip():
        raise FetchError(f"{label} must be nonempty")
    size = len(value.encode("utf-8"))
    if size > maximum:
        raise FetchError(f"{label} exceeds the {maximum}-byte fail-closed limit")
    return value


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise FetchError(f"{label} is not a canonical GitHub UTC timestamp")
    return value


def _read_regular_json(path: Path, *, label: str, maximum: int) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FetchError(f"cannot inspect {label}: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise FetchError(f"{label} must be a regular non-symlink file")
    if info.st_size > maximum:
        raise FetchError(f"{label} exceeds the {maximum}-byte limit")
    try:
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise FetchError(f"{label} exceeds the {maximum}-byte limit")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FetchError(f"{label} must be a JSON object")
    return value


def event_identity(path: Path) -> tuple[str, int, str, str]:
    event = _read_regular_json(
        path.absolute(),
        label="event",
        maximum=MAX_EVENT_BYTES,
    )
    try:
        pull = event["pull_request"]
        repository = _repository(pull["base"]["repo"]["full_name"], "event repository")
        number = _positive_integer(pull["number"], "event pull request number")
        base = _full_sha(pull["base"]["sha"], "event base SHA")
        head = _full_sha(pull["head"]["sha"], "event head SHA")
    except (KeyError, TypeError) as exc:
        raise FetchError("event is not a complete GitHub pull_request payload") from exc
    return repository, number, base, head


def explicit_closing_issue_numbers(body: str, repository: str) -> list[int]:
    """Return deduplicated same-repository closing references in body order."""

    owner, repo = repository.split("/", 1)
    numbers: list[int] = []
    for match in _CLOSING_REFERENCE_RE.finditer(body):
        referenced_owner = match.group("url_owner") or match.group("short_owner")
        referenced_repo = match.group("url_repo") or match.group("short_repo")
        if referenced_owner is not None:
            if (
                referenced_owner.casefold() != owner.casefold()
                or referenced_repo is None
                or referenced_repo.casefold() != repo.casefold()
            ):
                # Cross-repository text is not fetched or represented as acceptance
                # evidence; this snapshot has one exact repository authority.
                continue
        number = int(match.group("url_number") or match.group("short_number"))
        if number not in numbers:
            numbers.append(number)
        if len(numbers) > MAX_CLOSING_ISSUES:
            raise FetchError(
                f"PR body has more than {MAX_CLOSING_ISSUES} explicit same-repository "
                "closing issue references"
            )
    return numbers


def _api_get(token: str, route: str) -> dict[str, Any]:
    request = urllib.request.Request(
        API_ROOT + route,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nemoclaw-review-advisor",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", "replace")
        raise FetchError(
            f"GitHub REST {route} returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"GitHub REST {route} failed: {exc.reason}") from exc
    if len(raw) > MAX_API_RESPONSE_BYTES:
        raise FetchError(f"GitHub REST {route} exceeded the bounded response limit")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"GitHub REST {route} did not return valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FetchError(f"GitHub REST {route} did not return an object")
    return value


def build_context(
    *,
    repository: str,
    number: int,
    base_sha: str,
    head_sha: str,
    get_json: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    repository = _repository(repository)
    number = _positive_integer(number, "pull request number")
    base_sha = _full_sha(base_sha, "base SHA")
    head_sha = _full_sha(head_sha, "head SHA")

    pull = get_json(f"/repos/{repository}/pulls/{number}")
    try:
        actual_repository = _repository(
            pull["base"]["repo"]["full_name"],
            "GitHub PR repository",
        )
        actual_number = _positive_integer(pull["number"], "GitHub PR number")
        actual_base = _full_sha(pull["base"]["sha"], "GitHub PR base SHA")
        actual_head = _full_sha(pull["head"]["sha"], "GitHub PR head SHA")
    except (KeyError, TypeError) as exc:
        raise FetchError("GitHub PR response is missing exact identity fields") from exc
    expected_identity = (repository.casefold(), number, base_sha, head_sha)
    actual_identity = (
        actual_repository.casefold(),
        actual_number,
        actual_base,
        actual_head,
    )
    if actual_identity != expected_identity:
        raise FetchError(
            "GitHub PR identity does not match the requested repository, number, base, and head"
        )
    if pull.get("state") != "open":
        raise FetchError("GitHub PR is not open")

    title = _bounded_text(
        pull.get("title"),
        "PR title",
        maximum=MAX_PR_TITLE_BYTES,
        empty=False,
    )
    body = _bounded_text(pull.get("body"), "PR body", maximum=MAX_PR_BODY_BYTES)
    issue_numbers = explicit_closing_issue_numbers(body, repository)
    issues: list[dict[str, Any]] = []
    for issue_number in issue_numbers:
        issue = get_json(f"/repos/{repository}/issues/{issue_number}")
        actual_issue_number = _positive_integer(
            issue.get("number"),
            f"closing issue #{issue_number} number",
        )
        if actual_issue_number != issue_number:
            raise FetchError(
                f"closing issue #{issue_number} response has a mismatched number"
            )
        if "pull_request" in issue:
            raise FetchError(
                f"explicit closing reference #{issue_number} resolves to a pull request, "
                "not an issue"
            )
        state = issue.get("state")
        if state not in ("open", "closed"):
            raise FetchError(f"closing issue #{issue_number} has an invalid state")
        issues.append(
            {
                "number": issue_number,
                "title": _bounded_text(
                    issue.get("title"),
                    f"closing issue #{issue_number} title",
                    maximum=MAX_ISSUE_TITLE_BYTES,
                    empty=False,
                ),
                "body": _bounded_text(
                    issue.get("body"),
                    f"closing issue #{issue_number} body",
                    maximum=MAX_ISSUE_BODY_BYTES,
                ),
                "state": state,
                "updated_at": _timestamp(
                    issue.get("updated_at"),
                    f"closing issue #{issue_number} updated_at",
                ),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "kind": "github-rest-current-pr",
            "mutable_review_comments_included": False,
            "closing_link_detection": "explicit-body-keywords",
        },
        "repository": repository,
        "pull_request_number": number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pull_request": {
            "title": title,
            "body": body,
            "updated_at": _timestamp(pull.get("updated_at"), "PR updated_at"),
        },
        "closing_issues": issues,
    }


def _write_atomic(path: Path, data: bytes) -> None:
    if len(data) > MAX_OUTPUT_BYTES:
        raise FetchError(
            f"acceptance snapshot exceeds the {MAX_OUTPUT_BYTES}-byte output limit"
        )
    parent = path.parent.resolve(strict=True)
    target = parent / path.name
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if target.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise FetchError("output target must not be a symlink or special file")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--event", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    explicit = (args.repository, args.pr_number, args.base, args.head)
    if args.event:
        repository, number, base_sha, head_sha = event_identity(args.event)
        supplied = (args.repository, args.pr_number, args.base, args.head)
        expected = (repository, number, base_sha, head_sha)
        for label, actual, wanted in zip(
            ("--repository", "--pr-number", "--base", "--head"),
            supplied,
            expected,
            strict=True,
        ):
            if actual is not None and actual != wanted:
                raise FetchError(f"{label} does not match the event payload")
    else:
        if any(value is None for value in explicit):
            raise FetchError(
                "provide --event or --repository, --pr-number, --base, and --head"
            )
        repository = _repository(args.repository)
        number = _positive_integer(args.pr_number, "pull request number")
        base_sha = _full_sha(args.base, "base SHA")
        head_sha = _full_sha(args.head, "head SHA")

    token = os.environ.pop("NEMOCLAW_GITHUB_TOKEN", None)
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise FetchError("NEMOCLAW_GITHUB_TOKEN is required and must be bounded")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in token):
        raise FetchError("NEMOCLAW_GITHUB_TOKEN contains invalid control characters")

    context = build_context(
        repository=repository,
        number=number,
        base_sha=base_sha,
        head_sha=head_sha,
        get_json=lambda route: _api_get(token, route),
    )
    encoded = (
        json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    _write_atomic(args.output.absolute(), encoded)
    print("Acceptance snapshot written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FetchError, OSError) as error:
        print(f"fetch-pr-context: {error}", file=sys.stderr)
        raise SystemExit(1)
