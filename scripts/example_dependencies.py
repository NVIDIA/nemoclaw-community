#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate one example dependency contract and expose its install inputs."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_NAME = "dependencies.toml"
DEFAULT_SNAPSHOT = Path("scripts/catalog-maintenance-releases.json")
NEMOCLAW_TAG_PATTERN = re.compile(r"v\d+\.\d+\.\d+\Z")
VERSION_PATTERN = re.compile(r"v?\d+(?:\.\d+){1,3}\Z")
REF_PATTERN = re.compile(r"(?:v[A-Za-z0-9][A-Za-z0-9._-]*|[0-9a-f]{40})\Z")
IMAGE_PATTERN = re.compile(r"ghcr\.io/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
HARNESS_LABELS = {"hermes": "Hermes Agent", "openclaw": "OpenClaw"}
EXPORTED_VARIABLES = (
    "AGENT_SANDBOX_VERSION",
    "ENVOY_GATEWAY_CHART_VERSION",
    "HERMES_REF",
    "HERMES_TARBALL_SHA256",
    "HERMES_VERSION",
    "NEMOCLAW_AGENT",
    "NEMOCLAW_BASE_IMAGE",
    "NEMOCLAW_INSTALL_REF",
    "NEMOCLAW_INSTALL_TAG",
    "OPENCLAW_VERSION",
    "OPENSHELL_VERSION",
)


class DependencyContractError(ValueError):
    """Raised when an example dependency contract is unsafe or inconsistent."""


@dataclass(frozen=True)
class DependencyContract:
    """Authored install inputs for one example."""

    path: Path
    distribution: str
    version: str | None
    harness: str
    harness_version: str | None
    harness_ref: str | None
    openshell_version: str | None
    base_image: str | None
    harness_sha256: str | None
    agent_sandbox_version: str | None
    envoy_gateway_chart_version: str | None


@dataclass(frozen=True)
class ResolvedStack:
    """Public harness/runtime composition resolved from authored inputs."""

    distribution: str
    distribution_version: str | None
    distribution_commit: str | None
    harness: str
    harness_version: str
    openshell_version: str | None

    @property
    def harness_label(self) -> str:
        return HARNESS_LABELS[self.harness]


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DependencyContractError(f"{context} must be a TOML table.")
    return value


def _only_keys(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DependencyContractError(
            f"{context} contains unsupported keys: {', '.join(unknown)}."
        )


def _optional_string(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
    ):
        raise DependencyContractError(f"{context} must be a non-empty literal string.")
    return value


def _table_strings(
    value: dict[str, Any], keys: tuple[str, ...], path: Path, table: str
) -> dict[str, str | None]:
    _only_keys(value, set(keys), f"{path} [{table}]")
    return {
        key: _optional_string(value.get(key), f"{path} {table}.{key}")
        for key in keys
    }


def _require_pattern(
    value: str | None, pattern: re.Pattern[str], message: str
) -> None:
    if value is None or pattern.fullmatch(value) is None:
        raise DependencyContractError(message)


def _parse_contract_toml(source: str, path: Path) -> dict[str, Any]:
    """Parse the deliberately small TOML subset supported on Python 3.10."""

    result: dict[str, Any] = {}
    current = result
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        section = re.fullmatch(r"\[([a-z_]+)\]", line)
        if section:
            name = section.group(1)
            if name in result:
                raise DependencyContractError(
                    f"Duplicate TOML section {name!r} in {path}:{line_number}."
                )
            current = {}
            result[name] = current
            continue
        assignment = re.fullmatch(r"([a-z_][a-z0-9_]*)\s*=\s*(.+)", line)
        if assignment is None:
            raise DependencyContractError(
                f"Unsupported TOML syntax in {path}:{line_number}."
            )
        key, encoded = assignment.groups()
        if key in current:
            raise DependencyContractError(
                f"Duplicate TOML key {key!r} in {path}:{line_number}."
            )
        if encoded == "1":
            parsed: Any = 1
        elif (
            len(encoded) >= 2
            and encoded[0] == encoded[-1] == "'"
            and "'" not in encoded[1:-1]
        ):
            parsed = encoded[1:-1]
        else:
            try:
                parsed = json.loads(encoded)
            except json.JSONDecodeError as error:
                raise DependencyContractError(
                    f"Dependency values must be quoted strings in {path}:{line_number}."
                ) from error
        if isinstance(parsed, bool) or not isinstance(parsed, (int, str)):
            raise DependencyContractError(
                f"Unsupported dependency value in {path}:{line_number}."
            )
        current[key] = parsed
    return result


def load_dependency_contract(path: Path) -> DependencyContract:
    """Load and strictly validate one dependencies.toml file."""

    def optional_pattern(
        values: dict[str, str | None], key: str, pattern: re.Pattern[str], message: str
    ) -> None:
        if values[key] is not None:
            _require_pattern(values[key], pattern, f"{path} {message}")

    if path.is_symlink() or not path.is_file():
        raise DependencyContractError(f"Dependency contract must be a regular file: {path}")
    try:
        value = _parse_contract_toml(path.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeError) as error:
        raise DependencyContractError(
            f"Unable to read dependency contract {path}: {error}"
        ) from error
    _only_keys(value, {"schema_version", "stack", "deployment"}, str(path))
    if value.get("schema_version") != 1:
        raise DependencyContractError(f"{path} schema_version must be 1.")

    stack = _table_strings(
        _object(value.get("stack"), f"{path} [stack]"),
        (
            "distribution",
            "version",
            "harness",
            "harness_version",
            "harness_ref",
            "openshell_version",
            "base_image",
            "harness_sha256",
        ),
        path,
        "stack",
    )
    distribution = stack["distribution"]
    harness = stack["harness"]
    if distribution not in {"nemoclaw", "direct"}:
        raise DependencyContractError(
            f"{path} stack.distribution must be nemoclaw or direct."
        )
    if harness not in HARNESS_LABELS:
        raise DependencyContractError(
            f"{path} stack.harness must be hermes or openclaw."
        )

    if distribution == "nemoclaw":
        _require_pattern(
            stack["version"],
            NEMOCLAW_TAG_PATTERN,
            f"{path} NemoClaw distribution requires an exact vX.Y.Z version.",
        )
        duplicates = sorted(
            key
            for key in (
                "harness_version",
                "harness_ref",
                "openshell_version",
                "base_image",
                "harness_sha256",
            )
            if stack[key] is not None
        )
        if duplicates:
            raise DependencyContractError(
                f"{path} NemoClaw already defines {', '.join(duplicates)}; remove the "
                'duplicate pins or use distribution = "direct".'
            )
    else:
        if stack["version"] is not None:
            raise DependencyContractError(
                f"{path} direct distribution cannot set stack.version."
            )
        _require_pattern(
            stack["harness_version"],
            VERSION_PATTERN,
            f"{path} direct distribution requires a numeric harness_version.",
        )
        optional_pattern(
            stack, "openshell_version", VERSION_PATTERN,
            "stack.openshell_version must be a numeric release version.",
        )
        if harness == "hermes" and stack["harness_ref"] is not None:
            optional_pattern(
                stack, "harness_ref", REF_PATTERN,
                "direct Hermes stack has an invalid harness_ref.",
            )
        elif harness == "openclaw" and stack["harness_ref"] is not None:
            raise DependencyContractError(
                f"{path} direct OpenClaw uses its package version and cannot set harness_ref.",
            )

    optional_pattern(
        stack, "base_image", IMAGE_PATTERN,
        "stack.base_image must be an immutable ghcr.io digest.",
    )
    optional_pattern(
        stack, "harness_sha256", SHA256_PATTERN,
        "stack.harness_sha256 must be a lowercase SHA-256 digest.",
    )
    if distribution == "direct" and harness == "hermes" and (
        (stack["harness_ref"] is None) != (stack["harness_sha256"] is None)
    ):
        raise DependencyContractError(
            f"{path} direct Hermes source installs must set harness_ref and "
            "harness_sha256 together."
        )
    if distribution == "direct" and harness == "openclaw" and stack["harness_sha256"]:
        raise DependencyContractError(
            f"{path} direct OpenClaw stacks cannot set harness_sha256."
        )

    deployment = _table_strings(
        _object(value.get("deployment", {}), f"{path} [deployment]"),
        ("agent_sandbox_version", "envoy_gateway_chart_version"),
        path,
        "deployment",
    )
    for key, version in deployment.items():
        optional_pattern(
            deployment, key, VERSION_PATTERN,
            f"deployment.{key} must be a numeric release version.",
        )

    assert distribution is not None and harness is not None
    return DependencyContract(
        path=path,
        **stack,
        **deployment,
    )


def load_stack_snapshot(path: Path) -> dict[str, Any]:
    """Load the deterministic catalog snapshot used for stack resolution."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DependencyContractError(f"Unable to read stack snapshot {path}: {error}") from error
    return _object(value, f"Stack snapshot {path}")


def _snapshot_version(value: Any, context: str) -> str:
    version = _optional_string(value, context)
    _require_pattern(version, VERSION_PATTERN, f"{context} is invalid.")
    assert version is not None
    return version


def resolve_dependency_contract(
    contract: DependencyContract, snapshot: dict[str, Any]
) -> ResolvedStack:
    """Resolve the exact harness and OpenShell target for one contract."""

    if contract.distribution == "direct":
        assert contract.harness_version is not None
        return ResolvedStack(
            distribution="direct",
            distribution_version=None,
            distribution_commit=None,
            harness=contract.harness,
            harness_version=contract.harness_version,
            openshell_version=contract.openshell_version,
        )

    stacks = _object(snapshot.get("nemoclaw_stacks"), "Snapshot nemoclaw_stacks")
    record = _object(
        stacks.get(contract.version), f"Snapshot NemoClaw stack {contract.version}"
    )
    commit = _optional_string(
        record.get("commit"), f"Snapshot NemoClaw {contract.version} commit"
    )
    if commit is None or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise DependencyContractError(
            f"Snapshot NemoClaw {contract.version} requires an exact commit."
        )
    harnesses = _object(
        record.get("harnesses"), f"Snapshot NemoClaw {contract.version} harnesses"
    )
    return ResolvedStack(
        distribution="nemoclaw",
        distribution_version=contract.version,
        distribution_commit=commit,
        harness=contract.harness,
        harness_version=_snapshot_version(
            harnesses.get(contract.harness),
            f"Snapshot NemoClaw {contract.version} harness version",
        ),
        openshell_version=_snapshot_version(
            record.get("openshell"),
            f"Snapshot NemoClaw {contract.version} OpenShell version",
        ),
    )


def resolved_environment(
    contract: DependencyContract, stack: ResolvedStack
) -> dict[str, str]:
    """Return allowlisted values consumed by example setup and validation."""

    environment: dict[str, str] = {}
    if stack.distribution == "nemoclaw":
        assert stack.distribution_version is not None
        assert stack.distribution_commit is not None
        environment.update(
            {
                "NEMOCLAW_INSTALL_TAG": stack.distribution_version,
                "NEMOCLAW_INSTALL_REF": stack.distribution_commit,
                "NEMOCLAW_AGENT": stack.harness,
            }
        )
    if stack.harness == "hermes":
        environment["HERMES_VERSION"] = stack.harness_version
        if contract.harness_ref is not None:
            environment["HERMES_REF"] = contract.harness_ref
    else:
        environment["OPENCLAW_VERSION"] = stack.harness_version
    if stack.openshell_version is not None:
        environment["OPENSHELL_VERSION"] = stack.openshell_version

    optional_exports = {
        "NEMOCLAW_BASE_IMAGE": contract.base_image,
        "HERMES_TARBALL_SHA256": contract.harness_sha256,
        "AGENT_SANDBOX_VERSION": contract.agent_sandbox_version,
        "ENVOY_GATEWAY_CHART_VERSION": contract.envoy_gateway_chart_version,
    }
    environment.update(
        {name: value for name, value in optional_exports.items() if value is not None}
    )
    return dict(sorted(environment.items()))


def _find_repo_root(start: Path) -> Path:
    for candidate in (start.absolute(), *start.absolute().parents):
        if (candidate / ".git").exists() or (candidate / DEFAULT_SNAPSHOT).is_file():
            return candidate
    raise DependencyContractError("Unable to find the repository root.")


def _manifest_path(example: Path) -> Path:
    return example if example.name == MANIFEST_NAME else example / MANIFEST_NAME


def resolve_example_stack(
    example: Path, snapshot_path: Path | None = None
) -> ResolvedStack:
    """Resolve one example for Python callers without spawning the CLI."""

    manifest = _manifest_path(example).absolute()
    contract = load_dependency_contract(manifest)
    snapshot = {}
    if contract.distribution == "nemoclaw":
        root = _find_repo_root(manifest.parent)
        snapshot = load_stack_snapshot(snapshot_path or root / DEFAULT_SNAPSHOT)
    return resolve_dependency_contract(contract, snapshot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", type=Path, help="Example directory or dependencies.toml.")
    parser.add_argument("--snapshot", type=Path, help="Override the resolved stack snapshot.")
    args = parser.parse_args(argv)
    manifest = _manifest_path(args.example).absolute()
    try:
        contract = load_dependency_contract(manifest)
        snapshot = {}
        if contract.distribution == "nemoclaw":
            root = _find_repo_root(manifest.parent)
            snapshot = load_stack_snapshot(args.snapshot or root / DEFAULT_SNAPSHOT)
        stack = resolve_dependency_contract(contract, snapshot)
        environment = resolved_environment(contract, stack)
    except DependencyContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print("unset " + " ".join(EXPORTED_VARIABLES))
    for name, value in environment.items():
        print(f"export {name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
