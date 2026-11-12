# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the facts that matter from the recipe policy files without a YAML library.

OpenShell 0.1 composes a sandbox's effective policy from two sources: the
sandbox policy and the profile of each attached provider. The recipe keeps
every network endpoint out of the sandbox policy and puts the one local
endpoint in the provider profile, so each file has its own check.

The scanner accepts only the plain block style that the recipe files use. It
reports any construct that could hide a value from a line scan, so an
unreadable file fails the check instead of passing it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlsplit

# The OpenShell name for the gateway host, where the recipe-owned Ollama runs.
ALLOWED_EGRESS_HOSTS = frozenset({"host.openshell.internal"})
# Effective-policy entries that attached providers contribute.
PROVIDER_POLICY_PREFIX = "_provider_"
ALLOWED_READ_WRITE = frozenset({"/sandbox", "/tmp", "/dev/null"})
# Paths that must never appear in the filesystem allowlist. /mnt carries the
# Windows drives inside WSL2. /srv holds the test canary file.
FORBIDDEN_PREFIXES = ("/mnt", "/srv", "/home", "/root", "/media", "/host", "/var", "/sys", "/boot")

_HOST_RE = re.compile(r"(?<![\w-])host:\s*[\"']?([^\"'\s,}#]+)")
_ENFORCEMENT_RE = re.compile(r"(?<![\w-])enforcement:\s*[\"']?([^\"'\s,}#]+)")
_PORT_RE = re.compile(r"(?<![\w-])port:\s*[\"']?(\d+)")
_ACCESS_RE = re.compile(r"(?<![\w-])access:\s*[\"']?([^\"'\s,}#]+)")
_TLS_RE = re.compile(r"(?<![\w-])tls:\s*[\"']?([^\"'\s,}#]+)")
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


def _values(pattern: "re.Pattern[str]", text: str) -> list[str]:
    return [m.group(1).lower() for m in pattern.finditer("\n".join(_strip_comments(text)))]


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
    """Return every reason the sandbox policy is not a local-only policy.

    The sandbox policy must declare no network endpoint. The provider profile
    supplies the only one.
    """
    problems = list(unsupported_constructs(text))

    for host in egress_hosts(text):
        problems.append("sandbox policy declares a network endpoint: " + host)

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


def check_profile(text: str, base_url: Optional[str] = None) -> list[str]:
    """Return every reason the provider profile is not a local-only profile.

    With `base_url`, the profile endpoint must also match the host and port of
    the URL that the sandbox calls.
    """
    problems = list(unsupported_constructs(text))

    hosts = egress_hosts(text)
    if not hosts:
        problems.append("no endpoint found; expected " + ", ".join(sorted(ALLOWED_EGRESS_HOSTS)))
    for host in hosts:
        if host not in ALLOWED_EGRESS_HOSTS:
            problems.append("endpoint host is not local-only: " + host)

    modes = enforcement_modes(text)
    if len(modes) != len(hosts):
        problems.append("each endpoint must declare an enforcement mode")
    for mode in modes:
        if mode != "enforce":
            problems.append("enforcement mode is not enforce: " + mode)

    # An access preset permits every path. The profile lists its paths instead.
    for preset in _values(_ACCESS_RE, text):
        problems.append("endpoint uses an access preset instead of rules: " + preset)
    for mode in _values(_TLS_RE, text):
        if mode == "skip":
            problems.append("endpoint skips inspection: tls: skip")
    if "allow:" not in "\n".join(_strip_comments(text)):
        problems.append("endpoint lists no allow rule")
    if not re.search(r"^credentials:\s*\[\]\s*$", "\n".join(_strip_comments(text)), re.MULTILINE):
        problems.append("profile must declare no credentials: the local server checks none")

    if base_url is not None:
        try:
            parts = urlsplit(base_url.strip())
            wanted_host = (parts.hostname or "").lower()
            wanted_port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            problems.append("base URL is not valid: " + base_url)
        else:
            ports = _values(_PORT_RE, text)
            if hosts != [wanted_host] or ports != [str(wanted_port)]:
                problems.append(
                    "profile endpoint %s does not match base URL %s:%d" % (
                        ",".join("%s:%s" % pair for pair in zip(hosts, ports)) or "none",
                        wanted_host, wanted_port,
                    )
                )
    return problems


def _network_policies(node: Any) -> list[dict]:
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "network_policies" and isinstance(value, dict):
                found.append(value)
            else:
                found.extend(_network_policies(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_network_policies(value))
    return found


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

    The effective policy is the sandbox policy plus one layer for each attached
    provider. Every network entry must come from a provider layer, and every
    host must be local. An empty or unreadable document is a failure. A policy
    that cannot be read back is not a verified policy.
    """
    if not document.strip():
        return ["effective policy is empty"]
    try:
        parsed = json.loads(document)
    except ValueError:
        return ["effective policy is not valid JSON"]
    problems = []
    for policies in _network_policies(parsed):
        for key in policies:
            if not key.startswith(PROVIDER_POLICY_PREFIX):
                problems.append("effective policy has a network entry from the sandbox policy: " + key)
    hosts = _hosts_in_json(parsed)
    if not hosts:
        return problems + ["effective policy lists no endpoint host; is the provider attached?"]
    return problems + ["effective policy permits a host that is not local-only: " + host
                       for host in hosts if host not in ALLOWED_EGRESS_HOSTS]
