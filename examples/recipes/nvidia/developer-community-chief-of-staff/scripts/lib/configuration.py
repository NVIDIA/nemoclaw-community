# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared, side-effect-free configuration helpers for recipe setup tools."""

from __future__ import annotations

import os
import re
import shlex
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULTS = {
    "SANDBOX_NAME": "hermes-direct",
    "OPENSHELL_GATEWAY": "openshell",
    "NEMOCLAW_MODEL": DEFAULT_MODEL,
    "NEMOCLAW_INFERENCE_PREFLIGHT": "1",
    "OUTLOOK_LOGIN_CACHE": "1",
    "NEMOCLAW_SLACK_RICH_BLOCKS": "true",
    "GITHUB_READONLY_REPO": "NVIDIA/OpenShell",
}
GATEWAY_ENDPOINTS = {
    "openshell": "https://127.0.0.1:17670",
    "snap-docker": "http://127.0.0.1:17670",
}
OUTLOOK_REQUIRED = (
    "OUTLOOK_TENANT_ID",
    "OUTLOOK_CLIENT_ID",
    "OUTLOOK_TARGET_MAILBOX",
    "OUTLOOK_REPLY_TO",
)
SLACK_REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")
SECRET_KEYS = frozenset(
    {
        "ATIF_RELAY_AUTH_TOKEN",
        "ATIF_RELAY_S3_ACCESS_KEY",
        "ATIF_RELAY_S3_SECRET_KEY",
        "COMPATIBLE_API_KEY",
        "DISCORD_BOT_TOKEN",
        "GITHUB_TOKEN",
        "NEMOCLAW_MINIO_ROOT_PASSWORD",
        "OPENAI_API_KEY",
        "SLACK_APP_TOKEN",
        "SLACK_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    }
)
ASSIGNMENT_RE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$"
)
ATIF_RELAY_HOSTNAME_RE = re.compile(
    r"^([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$"
)


class ConfigurationError(ValueError):
    """A configuration file cannot be parsed or validated safely."""


@dataclass(frozen=True)
class EnvDocument:
    """Parsed values plus the original lines needed for a preserving update."""

    lines: tuple[str, ...]
    values: dict[str, str]
    line_indexes: dict[str, int]


def parse_atif_relay_endpoint(endpoint: str) -> tuple[str, str, int]:
    """Validate and canonicalize the HTTPS origin contract from ``_lib.sh``."""
    prefix = "https://"
    if not endpoint.startswith(prefix):
        raise ConfigurationError("ATIF_RELAY_ENDPOINT must be an https:// URL")

    host_port = endpoint[len(prefix) :]
    if host_port.endswith("/"):
        host_port = host_port[:-1]
    if any(character in host_port for character in "/?#@"):
        raise ConfigurationError(
            "ATIF_RELAY_ENDPOINT must be an origin with no path, query, "
            "fragment, or user information"
        )
    if host_port.count(":") != 1:
        raise ConfigurationError(
            "ATIF_RELAY_ENDPOINT must use a hostname and one explicit port; "
            "IPv6 literals are not supported"
        )

    host, raw_port = host_port.split(":", 1)
    if not ATIF_RELAY_HOSTNAME_RE.fullmatch(host):
        raise ConfigurationError("ATIF_RELAY_ENDPOINT hostname is invalid")
    if not re.fullmatch(r"[0-9]{1,5}", raw_port):
        raise ConfigurationError("ATIF_RELAY_ENDPOINT port must be numeric")

    port = int(raw_port, 10)
    if not 1 <= port <= 65535:
        raise ConfigurationError("ATIF_RELAY_ENDPOINT port must be between 1 and 65535")
    return f"{prefix}{host}:{port}", host, port


def split_inline_comment(raw: str) -> tuple[str, str]:
    """Split a shell comment that begins after unquoted, unescaped whitespace."""
    single_quoted = False
    double_quoted = False
    escaped = False
    at_word_start = False
    for index, character in enumerate(raw):
        if escaped:
            escaped = False
            at_word_start = False
            continue
        if character == "\\" and not single_quoted:
            escaped = True
            continue
        if character == "'" and not double_quoted:
            single_quoted = not single_quoted
            at_word_start = False
            continue
        if character == '"' and not single_quoted:
            double_quoted = not double_quoted
            at_word_start = False
            continue
        if (
            character == "#"
            and not single_quoted
            and not double_quoted
            and at_word_start
        ):
            suffix_start = index
            while suffix_start and raw[suffix_start - 1].isspace():
                suffix_start -= 1
            return raw[:suffix_start], raw[suffix_start:]
        if not single_quoted and not double_quoted and character.isspace():
            at_word_start = True
        else:
            at_word_start = False
    return raw, ""


def reject_executable_shell_syntax(raw: str, key: str) -> None:
    """Reject shell operators that could execute code when lifecycle scripts source .env."""
    single_quoted = False
    double_quoted = False
    escaped = False
    for character in raw:
        if escaped:
            escaped = False
            continue
        if character == "\\" and not single_quoted:
            escaped = True
            continue
        if character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue
        if character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue
        if single_quoted:
            continue
        if character in "`$":
            raise ConfigurationError(
                f"{key} contains an unsupported shell operator or expansion"
            )
        if not double_quoted and character in ";&|<>":
            raise ConfigurationError(
                f"{key} contains an unsupported shell operator or expansion"
            )


def decode_value(raw: str, key: str) -> str:
    """Decode one shell-compatible assignment without executing the file."""
    if "\x00" in raw:
        raise ConfigurationError(f"{key} contains a NUL byte")
    raw, _comment = split_inline_comment(raw)
    reject_executable_shell_syntax(raw, key)
    if raw == "":
        return ""
    try:
        parts = shlex.split(raw, comments=False, posix=True)
    except ValueError as error:
        raise ConfigurationError(f"{key} has invalid shell quoting") from error
    if len(parts) != 1:
        raise ConfigurationError(
            f"{key} must use shell quoting when its value contains spaces"
        )
    return parts[0]


def parse_env_text(text: str) -> EnvDocument:
    """Parse assignments while preserving comments, order, and unknown lines."""
    lines = tuple(text.splitlines())
    values: dict[str, str] = {}
    line_indexes: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = ASSIGNMENT_RE.fullmatch(line)
        if not match:
            if line.strip() and not line.lstrip().startswith("#"):
                raise ConfigurationError(
                    f"line {index + 1} is not a supported assignment or comment"
                )
            continue
        key = match.group("key")
        if key in values:
            raise ConfigurationError(f"duplicate assignment for {key}")
        values[key] = decode_value(match.group("value"), key)
        line_indexes[key] = index
    return EnvDocument(lines=lines, values=values, line_indexes=line_indexes)


def read_env(path: Path) -> EnvDocument:
    if not path.exists():
        return EnvDocument(lines=(), values={}, line_indexes={})
    if not path.is_file():
        raise ConfigurationError(f"configuration path is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(
            f"configuration file is not valid UTF-8: {path}"
        ) from error
    except OSError as error:
        detail = error.strerror or error.__class__.__name__
        raise ConfigurationError(
            f"cannot read configuration file {path}: {detail}"
        ) from error
    return parse_env_text(text)


def encode_value(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ConfigurationError("configuration values must fit on one line")
    return shlex.quote(value)


def render_updates(
    document: EnvDocument,
    updates: Mapping[str, str],
    *,
    replace: bool = False,
) -> str:
    """Render explicit updates and preserve every unselected existing line."""
    if replace:
        lines = [
            "# Generated by scripts/configure.py. Advanced settings remain in .env.example.",
        ]
        for key, value in updates.items():
            lines.append(f"{key}={encode_value(value)}")
        return "\n".join(lines) + "\n"

    lines = list(document.lines)
    append_lines: list[str] = []
    for key, value in updates.items():
        rendered = f"{key}={encode_value(value)}"
        if key in document.line_indexes:
            index = document.line_indexes[key]
            if document.values[key] == value:
                continue
            match = ASSIGNMENT_RE.fullmatch(lines[index])
            assert match is not None
            _expression, comment = split_inline_comment(match.group("value"))
            lines[index] = f"{match.group('prefix')}{rendered}{comment}"
        else:
            append_lines.append(rendered)
    if append_lines:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("# Added by scripts/configure.py.")
        lines.extend(append_lines)
    return "\n".join(lines) + "\n"


def write_env(path: Path, text: str) -> None:
    """Atomically write the secret-bearing file with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def resolved_values(
    document: EnvDocument,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve defaults, then process inputs, then the file sourced by bring-up."""
    result = dict(DEFAULTS)
    result.update({key: value for key, value in (environment or {}).items() if value})
    result.update(document.values)
    gateway = result.get("OPENSHELL_GATEWAY", DEFAULTS["OPENSHELL_GATEWAY"])
    if not result.get("OPENSHELL_GATEWAY_ENDPOINT") and gateway in GATEWAY_ENDPOINTS:
        result["OPENSHELL_GATEWAY_ENDPOINT"] = GATEWAY_ENDPOINTS[gateway]
    return result


def profile_keys(profile: str) -> tuple[str, ...]:
    if profile == "slack":
        return SLACK_REQUIRED
    if profile == "outlook":
        return OUTLOOK_REQUIRED
    if profile == "both":
        return OUTLOOK_REQUIRED + SLACK_REQUIRED
    raise ConfigurationError(f"unknown messaging profile: {profile}")


def profile_errors(
    values: Mapping[str, str], *, require_channel: bool = True
) -> list[str]:
    """Return names-only errors for partial or absent messaging profiles."""
    errors: list[str] = []
    enabled_profiles = 0
    for name, required in (("Outlook", OUTLOOK_REQUIRED), ("Slack", SLACK_REQUIRED)):
        present = [key for key in required if values.get(key)]
        missing = [key for key in required if not values.get(key)]
        if present and missing:
            errors.append(f"partial {name} configuration; missing {', '.join(missing)}")
        elif present:
            enabled_profiles += 1
    if require_channel and enabled_profiles == 0:
        errors.append("no messaging profile is fully configured")
    return errors


def enabled_profiles(values: Mapping[str, str]) -> tuple[str, ...]:
    profiles: list[str] = []
    if all(values.get(key) for key in OUTLOOK_REQUIRED):
        profiles.append("Outlook")
    if all(values.get(key) for key in SLACK_REQUIRED):
        profiles.append("Slack")
    return tuple(profiles)
