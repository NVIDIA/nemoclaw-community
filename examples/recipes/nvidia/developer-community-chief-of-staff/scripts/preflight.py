#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run read-only configuration and prerequisite checks before recipe bring-up."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLE_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXAMPLE_DIR.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import inference_preflight  # noqa: E402
import slack_socket_preflight  # noqa: E402
import tavily_search_preflight  # noqa: E402
from scripts.example_dependencies import (  # noqa: E402
    DependencyContractError,
    resolve_example_stack,
)
from lib.configuration import (  # noqa: E402
    DEFAULTS,
    GATEWAY_ENDPOINTS,
    GITHUB_REPOSITORY_RE,
    OUTLOOK_REQUIRED,
    SECRET_KEYS,
    SLACK_REQUIRED,
    ConfigurationError,
    enabled_profiles,
    github_readonly_repositories,
    parse_atif_relay_endpoint,
    profile_errors,
    read_env,
    resolved_values,
)


def resolve_expected_openshell_version() -> str:
    """Resolve the exact CLI pin through the repository dependency contract."""

    try:
        value = resolve_example_stack(EXAMPLE_DIR).openshell_version
    except DependencyContractError as error:
        raise RuntimeError(f"Could not resolve dependencies.toml: {error}") from error
    if not isinstance(value, str) or re.fullmatch(r"\d+\.\d+\.\d+", value) is None:
        raise RuntimeError(
            "dependencies.toml did not resolve an exact OpenShell version"
        )
    return value


EXPECTED_OPENSHELL_VERSION = resolve_expected_openshell_version()
SLACK_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,}$")


@dataclass(frozen=True)
class Check:
    name: str
    scope: str
    status: str
    detail: str
    remediation: str = ""


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
PortAvailable = Callable[[int], bool]
EndpointReachable = Callable[[str, float], bool]


def run_command(
    command: Sequence[str], timeout: float = 5.0
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(list(command), 124, "", "")


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def endpoint_is_reachable(endpoint: str, timeout: float = 2.0) -> bool:
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


def integer_value(
    values: Mapping[str, str], key: str, default: int
) -> tuple[int, str | None]:
    raw = values.get(key, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default, f"{key} must be an integer"
    if not 1 <= value <= 65535:
        return default, f"{key} must be between 1 and 65535"
    return value, None


def redact(text: str, values: Mapping[str, str]) -> str:
    sanitized = text
    for key in SECRET_KEYS:
        value = values.get(key, "")
        if value:
            sanitized = sanitized.replace(value, "<redacted>")
    return sanitized


def credential_status(values: Mapping[str, str]) -> dict[str, str]:
    """Report credential presence without returning credential values."""
    inference_key = values.get("OPENAI_API_KEY") or values.get("COMPATIBLE_API_KEY")
    credentials = {
        "Inference API key": bool(inference_key),
        "Slack bot access token": bool(values.get("SLACK_BOT_TOKEN")),
        "Slack app-level token": bool(values.get("SLACK_APP_TOKEN")),
        "GitHub access token": bool(values.get("GITHUB_TOKEN")),
        "Tavily API key": bool(values.get("TAVILY_API_KEY")),
        "ATIF relay access token": bool(values.get("ATIF_RELAY_AUTH_TOKEN")),
    }
    return {
        name: "configured" if configured else "not configured"
        for name, configured in credentials.items()
    }


def configuration_checks(env_file: Path, values: Mapping[str, str]) -> list[Check]:
    checks: list[Check] = []
    if env_file.is_file():
        permissions = stat.S_IMODE(env_file.stat().st_mode)
        if permissions & (stat.S_IRWXG | stat.S_IRWXO):
            checks.append(
                Check(
                    "configuration file permissions",
                    "local",
                    "FAIL",
                    "the configuration file is accessible beyond its owner",
                    f"Run: chmod 600 {env_file}",
                )
            )
        else:
            checks.append(
                Check(
                    "configuration file permissions",
                    "local",
                    "PASS",
                    "owner-only access",
                )
            )
    else:
        checks.append(
            Check(
                "configuration file",
                "configuration",
                "FAIL",
                "the configuration file does not exist",
                "Run: python3 scripts/configure.py",
            )
        )

    errors = profile_errors(values)
    checks.append(
        Check(
            "messaging configuration",
            "configuration",
            "FAIL" if errors else "PASS",
            "; ".join(errors) if errors else ", ".join(enabled_profiles(values)),
            "Run: python3 scripts/configure.py" if errors else "",
        )
    )

    inference_key = values.get("OPENAI_API_KEY") or values.get("COMPATIBLE_API_KEY")
    inference_setting = values.get("NEMOCLAW_INFERENCE_PREFLIGHT", "1")
    if inference_setting not in {"0", "1"}:
        checks.append(
            Check(
                "inference configuration",
                "configuration",
                "FAIL",
                "NEMOCLAW_INFERENCE_PREFLIGHT must be 0 or 1",
                "Set NEMOCLAW_INFERENCE_PREFLIGHT=1, or use 0 only for intentional offline setup",
            )
        )
    elif not inference_key and inference_setting == "1":
        checks.append(
            Check(
                "inference configuration",
                "configuration",
                "FAIL",
                "no inference API key is configured",
                "Set COMPATIBLE_API_KEY, or use the documented intentional offline bypass",
            )
        )
    else:
        checks.append(
            Check(
                "inference configuration",
                "configuration",
                "PASS" if inference_key else "WARN",
                "API key configured; value redacted"
                if inference_key
                else "intentional offline bypass enabled; the agent will have no inference",
            )
        )

    endpoint = values.get(
        "NEMOCLAW_ENDPOINT_URL",
        values.get("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    )
    try:
        inference_preflight.completion_url(endpoint)
        endpoint_status = Check(
            "inference endpoint",
            "configuration",
            "PASS",
            inference_preflight.display_endpoint(endpoint),
        )
    except inference_preflight.PreflightError as error:
        endpoint_status = Check(
            "inference endpoint",
            "configuration",
            "FAIL",
            str(error),
            "Set NEMOCLAW_ENDPOINT_URL to HTTPS or an allowed loopback HTTP endpoint",
        )
    checks.append(endpoint_status)

    if not values.get("NEMOCLAW_MODEL"):
        checks.append(
            Check(
                "inference model",
                "configuration",
                "FAIL",
                "NEMOCLAW_MODEL is empty",
                f"Set NEMOCLAW_MODEL={DEFAULTS['NEMOCLAW_MODEL']}",
            )
        )
    else:
        checks.append(
            Check(
                "inference model",
                "configuration",
                "PASS",
                values["NEMOCLAW_MODEL"],
            )
        )

    if values.get("NEMOCLAW_SLACK_RICH_BLOCKS", "true") not in {"true", "false"}:
        checks.append(
            Check(
                "Slack rich blocks",
                "configuration",
                "FAIL",
                "NEMOCLAW_SLACK_RICH_BLOCKS must be true or false",
            )
        )
    if all(values.get(key) for key in SLACK_REQUIRED):
        token_shapes_valid = values["SLACK_BOT_TOKEN"].startswith("xoxb-") and values[
            "SLACK_APP_TOKEN"
        ].startswith("xapp-")
        checks.append(
            Check(
                "Slack token formats",
                "configuration",
                "PASS" if token_shapes_valid else "FAIL",
                "bot and app-level token prefixes are valid"
                if token_shapes_valid
                else "expected an xoxb- bot access token and xapp- app-level token",
                "Update the Slack values with the documented token types"
                if not token_shapes_valid
                else "",
            )
        )
    if values.get("OUTLOOK_LOGIN_CACHE", "1") not in {"0", "1", "2"}:
        checks.append(
            Check(
                "Outlook login cache",
                "configuration",
                "FAIL",
                "OUTLOOK_LOGIN_CACHE must be 0, 1, or 2",
            )
        )
    try:
        repositories = github_readonly_repositories(values)
        repository_error = ""
    except ConfigurationError as error:
        repositories = ()
        repository_error = str(error)
    checks.append(
        Check(
            "GitHub read-only repositories",
            "configuration",
            "FAIL" if repository_error else "PASS",
            repository_error
            or f"{len(repositories)} configured: {', '.join(repositories)}",
            (
                "Set GITHUB_READONLY_REPOS to a comma-separated owner/repository list"
                if repository_error
                else ""
            ),
        )
    )

    tavily_key = values.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            tavily_search_preflight.validate_host_key(tavily_key)
            tavily_error = ""
        except tavily_search_preflight.TavilyPreflightError as error:
            tavily_error = str(error)
        checks.append(
            Check(
                "public web search",
                "configuration",
                "FAIL" if tavily_error else "PASS",
                tavily_error or "Tavily Search enabled; API key value redacted",
                "Set TAVILY_API_KEY to the host-held Tavily API key"
                if tavily_error
                else "",
            )
        )
    else:
        checks.append(
            Check(
                "public web search",
                "optional",
                "SKIP",
                "disabled; no Tavily provider or network policy will be attached",
            )
        )

    slack_ids = [
        item.strip()
        for item in values.get("SLACK_ALLOWED_IDS", "").split(",")
        if item.strip()
    ]
    invalid_ids = [item for item in slack_ids if not SLACK_ID_RE.fullmatch(item)]
    if invalid_ids:
        checks.append(
            Check(
                "Slack allowlist",
                "configuration",
                "FAIL",
                f"{len(invalid_ids)} member ID value(s) have an invalid format",
                "Use comma-separated Slack member IDs that start with U or W",
            )
        )
    elif all(values.get(key) for key in SLACK_REQUIRED):
        checks.append(
            Check(
                "Slack allowlist",
                "configuration",
                "PASS" if slack_ids else "WARN",
                f"{len(slack_ids)} member ID(s) configured"
                if slack_ids
                else "empty allowlist enables responses to every workspace member",
            )
        )
    return checks


def tool_checks(
    values: Mapping[str, str],
    *,
    command_runner: CommandRunner,
    endpoint_reachable: EndpointReachable,
) -> list[Check]:
    checks = [
        Check(
            "Python version",
            "local",
            "PASS" if sys.version_info >= (3, 10) else "FAIL",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Install Python 3.10 or newer" if sys.version_info < (3, 10) else "",
        )
    ]
    for command in ("git", "docker", "openshell", "curl", "openssl"):
        path = shutil.which(command)
        checks.append(
            Check(
                f"{command} command",
                "local",
                "PASS" if path else "FAIL",
                "available" if path else "not found in PATH",
                f"Install {command} and add it to PATH" if not path else "",
            )
        )

    if shutil.which("docker"):
        docker_info = command_runner(("docker", "info"), 8)
        checks.append(
            Check(
                "Docker daemon",
                "local",
                "PASS" if docker_info.returncode == 0 else "FAIL",
                "reachable" if docker_info.returncode == 0 else "not reachable",
                "Start the Docker daemon" if docker_info.returncode else "",
            )
        )
        compose = command_runner(("docker", "compose", "version"), 5)
        checks.append(
            Check(
                "Docker Compose",
                "local",
                "PASS" if compose.returncode == 0 else "FAIL",
                "available"
                if compose.returncode == 0
                else "docker compose is unavailable",
                "Install the Docker Compose plugin" if compose.returncode else "",
            )
        )

    if shutil.which("openshell"):
        version = command_runner(("openshell", "--version"), 5)
        version_text = (version.stdout or version.stderr).strip()
        match = re.search(r"\b(\d+\.\d+\.\d+)\b", version_text)
        installed = match.group(1) if match else "unknown"
        status = "PASS" if installed == EXPECTED_OPENSHELL_VERSION else "WARN"
        checks.append(
            Check(
                "OpenShell version",
                "local",
                status,
                installed,
                f"Install OpenShell {EXPECTED_OPENSHELL_VERSION} for the documented configuration"
                if status == "WARN"
                else "",
            )
        )
        gateway = values.get("OPENSHELL_GATEWAY", DEFAULTS["OPENSHELL_GATEWAY"])
        endpoint = values.get("OPENSHELL_GATEWAY_ENDPOINT") or GATEWAY_ENDPOINTS.get(
            gateway, ""
        )
        if endpoint:
            reachable = endpoint_reachable(endpoint, 2)
            checks.append(
                Check(
                    "OpenShell gateway endpoint",
                    "local",
                    "PASS" if reachable else "FAIL",
                    "reachable" if reachable else "not reachable",
                    "Start the configured OpenShell gateway service"
                    if not reachable
                    else "",
                )
            )
        else:
            checks.append(
                Check(
                    "OpenShell gateway endpoint",
                    "configuration",
                    "FAIL",
                    "no default endpoint is known for the configured gateway",
                    "Set OPENSHELL_GATEWAY_ENDPOINT",
                )
            )
        registered = command_runner(
            ("openshell", "gateway", "info", "--gateway", gateway), 5
        )
        checks.append(
            Check(
                "OpenShell gateway registration",
                "local",
                "PASS" if registered.returncode == 0 else "FAIL",
                "registered" if registered.returncode == 0 else "not registered",
                "Run scripts/01-gateway.sh after the endpoint is running"
                if registered.returncode
                else "",
            )
        )
        settings = command_runner(
            ("openshell", "settings", "get", "--global", "--gateway", gateway), 5
        )
        provider_v2 = settings.returncode == 0 and bool(
            re.search(r"providers_v2_enabled\s*=\s*true", settings.stdout)
        )
        checks.append(
            Check(
                "OpenShell provider v2",
                "local",
                "PASS" if provider_v2 else "FAIL",
                "enabled" if provider_v2 else "not enabled or unreadable",
                "Run: openshell settings set --global --key providers_v2_enabled --value true --yes"
                if not provider_v2
                else "",
            )
        )
    return checks


def local_port_checks(
    values: Mapping[str, str], *, port_available: PortAvailable
) -> list[Check]:
    source_port, source_error = integer_value(values, "SOURCE_ETL_API_PORT", 3100)
    postgres_port, postgres_error = integer_value(
        values, "SOURCE_ETL_POSTGRES_PORT", 5432
    )
    ports = {
        "Phoenix UI": 6006,
        "OpenTelemetry gRPC": 4317,
        "OpenTelemetry HTTP": 4318,
        "source API": source_port,
        "source PostgreSQL": postgres_port,
    }
    checks: list[Check] = []
    if source_error:
        checks.append(Check("source API port", "configuration", "FAIL", source_error))
        ports.pop("source API")
    if postgres_error:
        checks.append(
            Check("source PostgreSQL port", "configuration", "FAIL", postgres_error)
        )
        ports.pop("source PostgreSQL")
    if values.get("ATIF_EXPORT_MODE", "local") == "relay":
        relay_endpoint = values.get(
            "ATIF_RELAY_ENDPOINT", "https://host.openshell.internal:18443"
        )
        try:
            _canonical_endpoint, _relay_host, relay_port = parse_atif_relay_endpoint(
                relay_endpoint
            )
        except ConfigurationError as error:
            checks.append(
                Check(
                    "ATIF relay endpoint",
                    "configuration",
                    "FAIL",
                    str(error),
                )
            )
        else:
            ports["ATIF relay"] = relay_port
        if values.get("ATIF_RELAY_BACKEND") == "minio":
            ports["MinIO API"] = 9000
            ports["MinIO console"] = 9001
    for name, port in ports.items():
        available = port_available(port)
        checks.append(
            Check(
                f"{name} port",
                "local",
                "PASS" if available else "WARN",
                f"host port {port} is available"
                if available
                else f"host port {port} is already in use",
                "Confirm that the existing listener belongs to this recipe before bring-up"
                if not available
                else "",
            )
        )
    return checks


def optional_component_checks(values: Mapping[str, str]) -> list[Check]:
    checks: list[Check] = []
    ca_bundle = Path(
        values.get("NEMOCLAW_HOST_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")
    )
    ca_ready = (
        ca_bundle.is_absolute()
        and ca_bundle.is_file()
        and os.access(ca_bundle, os.R_OK)
    )
    checks.append(
        Check(
            "host certificate authority (CA) bundle",
            "local",
            "PASS" if ca_ready else "FAIL",
            "readable regular file"
            if ca_ready
            else "path is not a readable absolute file",
            "Set NEMOCLAW_HOST_CA_BUNDLE to the host's readable CA bundle"
            if not ca_ready
            else "",
        )
    )
    checks.append(
        Check(
            "authenticated GitHub reads",
            "optional",
            "PASS" if values.get("GITHUB_TOKEN") else "SKIP",
            "enabled; access token value redacted"
            if values.get("GITHUB_TOKEN")
            else "disabled; anonymous requests remain subject to GitHub limits",
        )
    )
    github_etl = values.get("SOURCE_ETL_GITHUB_ENABLED", "0")
    github_etl_repository = values.get("SOURCE_ETL_GITHUB_REPO", "NVIDIA/NemoClaw")
    github_etl_valid = bool(GITHUB_REPOSITORY_RE.fullmatch(github_etl_repository))
    checks.append(
        Check(
            "GitHub source ETL",
            "optional",
            "PASS"
            if github_etl == "1" and github_etl_valid
            else "SKIP"
            if github_etl == "0"
            else "FAIL",
            f"enabled for {github_etl_repository}"
            if github_etl == "1" and github_etl_valid
            else "disabled"
            if github_etl == "0"
            else "expected enable flag 0 or 1 and repository owner/name",
        )
    )
    export_mode = values.get("ATIF_EXPORT_MODE", "local")
    if export_mode == "local":
        checks.append(
            Check("ATIF relay export", "optional", "SKIP", "local export selected")
        )
    elif export_mode == "relay":
        backend = values.get("ATIF_RELAY_BACKEND", "")
        valid = backend in {"s3", "minio", "s3-compatible"}
        missing: list[str] = []
        if backend in {"s3", "s3-compatible"} and not values.get("ATIF_RELAY_BUCKET"):
            missing.append("ATIF_RELAY_BUCKET")
        if backend == "s3-compatible":
            for key in (
                "ATIF_RELAY_S3_ENDPOINT",
                "ATIF_RELAY_S3_ACCESS_KEY",
                "ATIF_RELAY_S3_SECRET_KEY",
            ):
                if not values.get(key):
                    missing.append(key)
        valid = valid and not missing
        detail = (
            f"relay enabled with {backend}"
            if valid
            else "missing or invalid values: "
            + ", ".join(missing or ["ATIF_RELAY_BACKEND"])
        )
        checks.append(
            Check(
                "ATIF relay export",
                "optional",
                "PASS" if valid else "FAIL",
                detail,
                "Complete the selected relay backend values in .env"
                if not valid
                else "",
            )
        )
    else:
        checks.append(
            Check(
                "ATIF relay export",
                "optional",
                "FAIL",
                "ATIF_EXPORT_MODE must be local or relay",
            )
        )
    return checks


def external_checks(values: Mapping[str, str], timeout: float) -> list[Check]:
    checks: list[Check] = []
    inference_setting = values.get("NEMOCLAW_INFERENCE_PREFLIGHT", "1")
    inference_key = values.get("OPENAI_API_KEY") or values.get("COMPATIBLE_API_KEY")
    if inference_setting == "1" and inference_key:
        endpoint = values.get(
            "NEMOCLAW_ENDPOINT_URL",
            values.get("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        )
        try:
            inference_preflight.run_preflight(
                endpoint,
                values.get("NEMOCLAW_MODEL", DEFAULTS["NEMOCLAW_MODEL"]),
                inference_key,
                timeout,
            )
            checks.append(
                Check(
                    "inference endpoint and structured tool call",
                    "external",
                    "PASS",
                    "validated by scripts/inference_preflight.py",
                )
            )
        except inference_preflight.PreflightError as error:
            checks.append(
                Check(
                    "inference endpoint and structured tool call",
                    "external",
                    "FAIL",
                    str(error),
                )
            )
    else:
        checks.append(
            Check(
                "inference endpoint and structured tool call",
                "external",
                "SKIP",
                "not configured for an external check",
            )
        )

    tavily_key = values.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            tavily_search_preflight.run_preflight(tavily_key, timeout)
            checks.append(
                Check(
                    "Tavily Search",
                    "external",
                    "PASS",
                    "one bounded search request succeeded; API key value redacted",
                )
            )
        except tavily_search_preflight.TavilyPreflightError as error:
            checks.append(Check("Tavily Search", "external", "FAIL", str(error)))
    else:
        checks.append(
            Check("Tavily Search", "external", "SKIP", "public web search is disabled")
        )

    if all(values.get(key) for key in SLACK_REQUIRED):
        try:
            slack_socket_preflight.run_preflight(values["SLACK_APP_TOKEN"], timeout)
            checks.append(
                Check(
                    "Slack Socket Mode",
                    "external",
                    "PASS",
                    "validated by scripts/slack_socket_preflight.py",
                )
            )
        except slack_socket_preflight.SlackPreflightError as error:
            checks.append(Check("Slack Socket Mode", "external", "FAIL", str(error)))
    else:
        checks.append(
            Check("Slack Socket Mode", "external", "SKIP", "Slack is disabled")
        )

    if all(values.get(key) for key in OUTLOOK_REQUIRED):
        checks.append(
            Check(
                "Outlook access",
                "external",
                "SKIP",
                "device-code sign-in remains an explicit bring-up step",
            )
        )
    else:
        checks.append(
            Check("Outlook access", "external", "SKIP", "Outlook is disabled")
        )
    return checks


def skipped_external_checks(values: Mapping[str, str]) -> list[Check]:
    checks = [
        Check(
            "inference endpoint and structured tool call",
            "external",
            "SKIP",
            "not contacted; rerun with --external",
        )
    ]
    tavily_detail = (
        "not contacted; rerun with --external"
        if values.get("TAVILY_API_KEY")
        else "public web search is disabled"
    )
    checks.append(Check("Tavily Search", "external", "SKIP", tavily_detail))
    slack_detail = (
        "not contacted; rerun with --external"
        if all(values.get(key) for key in SLACK_REQUIRED)
        else "Slack is disabled"
    )
    checks.append(Check("Slack Socket Mode", "external", "SKIP", slack_detail))
    outlook_detail = (
        "device-code sign-in remains an explicit bring-up step"
        if all(values.get(key) for key in OUTLOOK_REQUIRED)
        else "Outlook is disabled"
    )
    checks.append(Check("Outlook access", "external", "SKIP", outlook_detail))
    return checks


def next_command(checks: Sequence[Check], *, external: bool) -> str:
    failed = [check for check in checks if check.status == "FAIL"]
    if any(check.scope == "configuration" for check in failed):
        return "python3 scripts/configure.py"
    if failed:
        if external and all(check.scope == "external" for check in failed):
            return "python3 scripts/preflight.py --external"
        return "python3 scripts/preflight.py"
    if not external:
        return "python3 scripts/preflight.py --external"
    return "bash scripts/bring-up.sh"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=EXAMPLE_DIR / ".env")
    parser.add_argument(
        "--external",
        action="store_true",
        help="Contact the configured inference, Tavily, and Slack services with bounded checks",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Print redacted JSON")
    return parser


def run_preflight(
    env_file: Path,
    *,
    environment: Mapping[str, str] | None = None,
    external: bool = False,
    timeout: float = 10.0,
    command_runner: CommandRunner = run_command,
    port_available: PortAvailable = port_is_available,
    endpoint_reachable: EndpointReachable = endpoint_is_reachable,
) -> tuple[dict[str, object], int]:
    if environment is None:
        environment = os.environ
    document = read_env(env_file)
    values = resolved_values(document, environment)
    checks = configuration_checks(env_file, values)
    checks.extend(
        tool_checks(
            values,
            command_runner=command_runner,
            endpoint_reachable=endpoint_reachable,
        )
    )
    checks.extend(local_port_checks(values, port_available=port_available))
    checks.extend(optional_component_checks(values))
    checks.extend(
        external_checks(values, timeout)
        if external
        else skipped_external_checks(values)
    )
    checks = [
        Check(
            item.name,
            item.scope,
            item.status,
            redact(item.detail, values),
            redact(item.remediation, values),
        )
        for item in checks
    ]
    command = next_command(checks, external=external)
    result: dict[str, object] = {
        "ok": not any(check.status == "FAIL" for check in checks),
        "external_checks_requested": external,
        "resolved": {
            "sandbox": values.get("SANDBOX_NAME", DEFAULTS["SANDBOX_NAME"]),
            "gateway": values.get("OPENSHELL_GATEWAY", DEFAULTS["OPENSHELL_GATEWAY"]),
            "model": values.get("NEMOCLAW_MODEL", DEFAULTS["NEMOCLAW_MODEL"]),
            "messaging_profiles": list(enabled_profiles(values)),
            "credential_status": credential_status(values),
        },
        "checks": [asdict(check) for check in checks],
        "next_command": command,
    }
    return result, 0 if result["ok"] else 1


def print_text(result: Mapping[str, object]) -> None:
    resolved = result["resolved"]
    assert isinstance(resolved, dict)
    print("Resolved configuration (credentials redacted):")
    print(f"  Sandbox: {resolved['sandbox']}")
    print(f"  Gateway: {resolved['gateway']}")
    print(f"  Model: {resolved['model']}")
    profiles = resolved["messaging_profiles"]
    assert isinstance(profiles, list)
    print(f"  Messaging profiles: {', '.join(profiles) or 'none'}")
    credentials = resolved["credential_status"]
    assert isinstance(credentials, dict)
    print("  Credentials (values redacted):")
    for name, status in credentials.items():
        print(f"    {name}: {status}")
    print("\nChecks:")
    checks = result["checks"]
    assert isinstance(checks, list)
    for item in checks:
        assert isinstance(item, dict)
        print(
            f"  [{item['status']}] [{item['scope']}] {item['name']}: {item['detail']}"
        )
        if item["remediation"]:
            print(f"    Remediation: {item['remediation']}")
    print(f"\nResult: {'PASS' if result['ok'] else 'FAIL'}")
    print(f"Next command: {result['next_command']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 60:
        print(
            "--timeout must be greater than 0 and at most 60 seconds", file=sys.stderr
        )
        return 2
    try:
        result, exit_code = run_preflight(
            args.env_file,
            external=args.external,
            timeout=args.timeout,
        )
    except ConfigurationError as error:
        result = {
            "ok": False,
            "external_checks_requested": args.external,
            "resolved": {
                "sandbox": DEFAULTS["SANDBOX_NAME"],
                "gateway": DEFAULTS["OPENSHELL_GATEWAY"],
                "model": DEFAULTS["NEMOCLAW_MODEL"],
                "messaging_profiles": [],
                "credential_status": credential_status({}),
            },
            "checks": [
                asdict(Check("configuration file", "configuration", "FAIL", str(error)))
            ],
            "next_command": "python3 scripts/configure.py",
        }
        exit_code = 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print_text(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
