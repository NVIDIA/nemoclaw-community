# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the facts that matter from the sandbox policy without a YAML library.

The scanner accepts only the plain block style that the recipe policy uses.
It reports any construct that could hide a value from a line scan, so an
unreadable policy fails the check instead of passing it.
"""

from __future__ import annotations

import json
import re
from typing import Any

ALLOWED_EGRESS_HOSTS = frozenset({"inference.local"})
ALLOWED_READ_WRITE = frozenset({"/sandbox", "/tmp", "/dev/null"})
# Paths that must never appear in the filesystem allowlist. /mnt carries the
# Windows drives inside WSL2. /srv holds the test canary file.
FORBIDDEN_PREFIXES = ("/mnt", "/srv", "/home", "/root", "/media", "/host", "/var", "/sys", "/boot")

_HOST_RE = re.compile(r"(?<![\w-])host:\s*[\"']?([^\"'\s,}#]+)")
_ENFORCEMENT_RE = re.compile(r"(?<![\w-])enforcement:\s*[\"']?([^\"'\s,}#]+)")
_TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):")
_SUB_KEY_RE = re.compile(r"^\s+([A-Za-z_][\w-]*):\s*$")
_ITEM_RE = re.compile(r"^\s+-\s+[\"']?([^\"'\s#]+)[\"']?\s*$")


def _strip_comments(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s+#.*$", "", raw).rstrip())
    return lines


def unsupported_constructs(text: str) -> list[str]:
    """Return the YAML constructs that this scanner does not read."""
    problems = []
    for number, line in enumerate(_strip_comments(text), start=1):
        if "\t" in line:
            problems.append("line %d: tab character" % number)
        if re.search(r"(^|\s)[&*][A-Za-z_]", line):
            problems.append("line %d: anchor or alias" % number)
        if "<<" in line:
            problems.append("line %d: merge key" % number)
        if re.search(r":\s*[|>][+-]?\s*$", line):
            problems.append("line %d: block scalar" % number)
    return problems


def egress_hosts(text: str) -> list[str]:
    return [m.group(1).lower() for m in _HOST_RE.finditer("\n".join(_strip_comments(text)))]


def enforcement_modes(text: str) -> list[str]:
    return [m.group(1).lower() for m in _ENFORCEMENT_RE.finditer("\n".join(_strip_comments(text)))]


def filesystem_paths(text: str) -> dict[str, list[str]]:
    """Return the `read_only` and `read_write` lists of `filesystem_policy`."""
    found: dict[str, list[str]] = {"read_only": [], "read_write": []}
    section = None
    sub_key = None
    for line in _strip_comments(text):
        if not line.strip():
            continue
        top = _TOP_KEY_RE.match(line)
        if top:
            section = top.group(1)
            sub_key = None
            continue
        if section != "filesystem_policy":
            continue
        sub = _SUB_KEY_RE.match(line)
        if sub:
            sub_key = sub.group(1)
            continue
        item = _ITEM_RE.match(line)
        if item and sub_key in found:
            found[sub_key].append(item.group(1))
    return found


def check_policy(text: str) -> list[str]:
    """Return every reason the policy is not a local-only policy."""
    problems = list(unsupported_constructs(text))

    hosts = egress_hosts(text)
    if not hosts:
        problems.append("no egress endpoint found; expected inference.local")
    for host in hosts:
        if host not in ALLOWED_EGRESS_HOSTS:
            problems.append("egress host is not local-only: " + host)

    modes = enforcement_modes(text)
    if len(modes) != len(hosts):
        problems.append("each endpoint must declare an enforcement mode")
    for mode in modes:
        if mode != "enforce":
            problems.append("enforcement mode is not enforce: " + mode)

    paths = filesystem_paths(text)
    if not paths["read_only"] or not paths["read_write"]:
        problems.append("filesystem_policy must list read_only and read_write paths")
    for path in paths["read_write"]:
        if path not in ALLOWED_READ_WRITE:
            problems.append("read_write path is not accepted: " + path)
    for path in paths["read_only"] + paths["read_write"]:
        if path == "/" or not path.startswith("/"):
            problems.append("filesystem path is not accepted: " + path)
        if any(path == prefix or path.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES):
            problems.append("filesystem path exposes a protected location: " + path)
    return problems


def _hosts_in_json(node: Any) -> list[str]:
    hosts = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "host" and isinstance(value, str):
                hosts.append(value.lower())
            else:
                hosts.extend(_hosts_in_json(value))
    elif isinstance(node, list):
        for value in node:
            hosts.extend(_hosts_in_json(value))
    return hosts


def check_effective_policy(document: str) -> list[str]:
    """Check the JSON that OpenShell reports for a running sandbox.

    An empty or unreadable document is a failure. A policy that cannot be read
    back is not a verified policy.
    """
    if not document.strip():
        return ["effective policy is empty"]
    try:
        parsed = json.loads(document)
    except ValueError:
        return ["effective policy is not valid JSON"]
    hosts = _hosts_in_json(parsed)
    if not hosts:
        return ["effective policy lists no endpoint host"]
    return ["effective policy permits a host that is not local-only: " + host
            for host in hosts if host not in ALLOWED_EGRESS_HOSTS]
