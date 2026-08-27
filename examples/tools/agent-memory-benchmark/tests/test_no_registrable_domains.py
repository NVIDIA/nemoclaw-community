# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Nothing this example publishes may present a registrable domain as fiction.

The corpus was sanitized onto RFC 2606 reserved domains, and a guard checked the
corpus. It did not check the results, so the published `answers.as-answered.jsonl`
artifacts shipped the pre-sanitization domain back out, and both reports listed
it in a reversible map. A boundary that only covers the inputs is not a boundary.
This scans every tracked file.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# RFC 2606 reserves these top-level domains outright, plus the second-level
# example.com / example.net / example.org.
RESERVED_TLDS = {"example", "test", "invalid", "localhost"}
RESERVED_SECOND_LEVEL = {"example.com", "example.net", "example.org"}

# Real infrastructure the example genuinely talks to or references. Each entry is
# a service this code actually uses, not a stand-in for fictional material. Adding
# one means asserting the same.
REAL_INFRASTRUCTURE = {
    "api.openai.com",        # the proxy's documented default upstream
    "api.anthropic.com",     # the other base URL the proxy rewrites
    "www.w3.org",            # the SVG namespace in docs/assets
    "127.0.0.1",             # the accounting proxy's loopback bind address
    "localhost",
}

# Dotted identifiers that are not hosts and cannot be stripped as code, because
# they sit in JSON data rather than in prose. Each one has been read in place.
# Adding an entry means someone looked and found a name, not a domain.
KNOWN_NON_DOMAINS = {
    "team.info",  # a Slack Web API method, quoted in a corpus rate-limit table
}

# A host is only interesting where it is used as one: in a URL or an email
# address. A bare token is checked too, but only when it ends in a real
# top-level domain -- otherwise every dotted identifier in the Python sources
# (`os.environ.get`, `sys.stdin.read`) reads as a domain.
_PUBLIC_TLDS = (
    "com|net|org|io|co|dev|ai|app|edu|gov|mil|info|biz|me|xyz|cloud|sh|to|us|uk|eu")
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_URL_HOST = re.compile(r"\b(?:https?|ftp)://([a-z0-9][a-z0-9.-]*)", re.IGNORECASE)
# The corpus doc_id for a chat day is `channel@2026-04-25`, which is not an
# address; require a real or reserved suffix so a date-and-extension is not read
# as a host.
_EMAIL_HOST = re.compile(
    rf"[\w.+-]+@([a-z0-9][a-z0-9.-]*\.(?:{_PUBLIC_TLDS}|example|test|invalid|localhost))"
    r"(?![\w-])", re.IGNORECASE)
_BARE_HOST = re.compile(
    rf"(?<![\w.@/-])([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)*\.(?:{_PUBLIC_TLDS}))"
    r"(?![\w-])", re.IGNORECASE)


def _tracked_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True)
    return [REPO / name for name in listed.stdout.split("\0") if name]


def _offending(text: str) -> set[str]:
    found = set()
    # A bare host is only believable in prose. Inside code, `team.info` is a
    # Slack API method and `os.environ.get` is a call -- both read as hosts and
    # neither is one. URLs and addresses are checked everywhere, including code.
    prose = _CODE_SPAN.sub(" ", _CODE_FENCE.sub(" ", text))
    hosts = {m.group(1) for pattern in (_URL_HOST, _EMAIL_HOST)
             for m in pattern.finditer(text)}
    hosts |= {m.group(1) for m in _BARE_HOST.finditer(prose)}
    for domain in hosts:
        domain = domain.lower().rstrip(".")
        labels = domain.split(".")
        if labels[-1] in RESERVED_TLDS:
            continue
        if ".".join(labels[-2:]) in RESERVED_SECOND_LEVEL:
            continue
        if domain in REAL_INFRASTRUCTURE or domain in KNOWN_NON_DOMAINS:
            continue
        found.add(domain)
    return found


def test_git_ls_files_finds_something():
    """If the listing breaks, the scan below would pass by scanning nothing."""
    assert len(_tracked_files()) > 100


@pytest.mark.parametrize("kind", ["results", "corpora", "everything else"])
def test_no_tracked_file_publishes_a_registrable_domain(kind):
    scopes = {
        "results": lambda p: p.parts[0] == "results",
        "corpora": lambda p: p.parts[0] in ("corpus_a", "corpus_b"),
        "everything else": lambda p: p.parts[0] not in ("results", "corpus_a", "corpus_b"),
    }
    offenders: dict[str, set[str]] = {}
    for path in _tracked_files():
        relative = path.relative_to(REPO)
        if not scopes[kind](relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        found = _offending(text)
        if found:
            offenders[str(relative)] = found
    assert not offenders, (
        f"tracked files under {kind!r} publish domains that are not reserved and "
        f"are not declared real infrastructure: {offenders}. A registrable domain "
        f"in published material is one someone else can own.")


# A filesystem path from the machine a run happened on is the same class of leak
# as a registrable domain: it names something outside the fiction. One published
# citation carried `/home/<user>/.../workspace/...`, which published a username,
# a directory layout and an internal project name in one string.
_ABSOLUTE_PATH = re.compile(r"(?:^|[\"'\s(\[])((?:/home/|/Users/|[A-Za-z]:\\\\Users\\\\)[^\"'\s,\]\)]+)")
_HOME_SHORTHAND = re.compile(r"(?:^|[\"'\s(\[])(~/[^\"'\s,\]\)]+)")

# Paths that are instructions to a reader rather than a record of a machine.
DOCUMENTED_PATHS = {
    "~/src/my-system/.venv/bin/python",  # the README's worked example of an env override
}


@pytest.mark.parametrize("kind", ["results", "everything else"])
def test_no_tracked_file_publishes_a_path_from_someone_s_machine(kind):
    """A published artifact must not carry the filesystem it was produced on."""
    in_results = lambda p: p.parts[0] == "results"
    scope = in_results if kind == "results" else (lambda p: not in_results(p))
    offenders: dict[str, set[str]] = {}
    for path in _tracked_files():
        relative = path.relative_to(REPO)
        if not scope(relative) or path == Path(__file__).resolve():
            continue  # this file spells the patterns out; it matches itself
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        found = {m.group(1) for m in _ABSOLUTE_PATH.finditer(text)}
        found |= {m.group(1) for m in _HOME_SHORTHAND.finditer(text)}
        found -= DOCUMENTED_PATHS
        if found:
            offenders[str(relative)] = found
    assert not offenders, (
        f"tracked files under {kind!r} publish absolute paths from a machine: "
        f"{offenders}. A citation should name what it cites, relative to the "
        f"corpus or the memory, not where the run happened to execute.")
