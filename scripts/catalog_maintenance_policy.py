#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Load the shared, strictly validated catalog maintenance policy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEPENDENCY_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
CHANNEL_PATTERN = re.compile(r"[A-Za-z0-9._-]+\Z")
LABEL_MARKUP_PATTERN = re.compile(r"[`*_~\[\]<>]")
THRESHOLD_NAMES = (
    "dependency_warning_days",
    "dependency_overdue_days",
    "review_overdue_days",
    "deprecation_days",
)


class MaintenancePolicyError(ValueError):
    """Raised when the shared maintenance policy is invalid."""


@dataclass(frozen=True)
class DependencyDefinition:
    """One direct compatibility boundary tracked by the catalog."""

    id: str
    label: str
    repository: str
    source: str
    channel: str | None = None


@dataclass(frozen=True)
class MaintenancePolicy:
    """Validated global freshness thresholds and dependency registry."""

    dependency_warning_days: int
    dependency_overdue_days: int
    review_overdue_days: int
    deprecation_days: int
    dependencies: tuple[DependencyDefinition, ...]

    @property
    def dependencies_by_id(self) -> dict[str, DependencyDefinition]:
        return {dependency.id: dependency for dependency in self.dependencies}


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaintenancePolicyError(f"{context} must be a JSON object.")
    return value


def _keys(
    value: dict[str, Any],
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - (optional or set()))
    if missing:
        raise MaintenancePolicyError(
            f"{context} is missing required keys: {', '.join(missing)}."
        )
    if unknown:
        raise MaintenancePolicyError(
            f"{context} contains unsupported keys: {', '.join(unknown)}."
        )


def load_maintenance_policy_file(path: Path) -> MaintenancePolicy:
    """Load one policy document through the schema shared by every caller."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise MaintenancePolicyError(f"Maintenance policy not found: {path}") from error
    except (OSError, UnicodeError) as error:
        raise MaintenancePolicyError(f"Unable to read maintenance policy {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise MaintenancePolicyError(
            f"Maintenance policy {path} is not valid JSON: line {error.lineno}, "
            f"column {error.colno}."
        ) from error

    document = _object(document, "Maintenance policy")
    policy_keys = {"schema_version", "thresholds", "dependencies"}
    _keys(document, policy_keys, "Maintenance policy")
    if document["schema_version"] != 1:
        raise MaintenancePolicyError("Maintenance policy schema_version must be 1.")

    thresholds = _object(document["thresholds"], "Maintenance policy thresholds")
    _keys(thresholds, set(THRESHOLD_NAMES), "Maintenance policy thresholds")
    threshold_values: dict[str, int] = {}
    for name in THRESHOLD_NAMES:
        value = thresholds[name]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MaintenancePolicyError(
                f"Maintenance threshold {name!r} must be a positive integer."
            )
        threshold_values[name] = value

    dependencies = _object(document["dependencies"], "Maintenance policy dependencies")
    if not dependencies:
        raise MaintenancePolicyError(
            "Maintenance policy dependencies must contain at least one dependency."
        )
    definitions: list[DependencyDefinition] = []
    labels: set[str] = set()
    for dependency_id, raw_definition in sorted(dependencies.items()):
        if not isinstance(dependency_id, str) or not DEPENDENCY_ID_PATTERN.fullmatch(
            dependency_id
        ):
            raise MaintenancePolicyError(
                f"Invalid maintenance dependency identifier: {dependency_id!r}."
            )
        context = f"Maintenance dependency {dependency_id!r}"
        definition = _object(raw_definition, context)
        _keys(definition, {"label", "repository", "source"}, context, {"channel"})
        label = definition["label"]
        repository = definition["repository"]
        source = definition["source"]
        channel = definition.get("channel")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > 60
            or LABEL_MARKUP_PATTERN.search(label)
        ):
            raise MaintenancePolicyError(f"{context} has an invalid label.")
        if label in labels:
            raise MaintenancePolicyError(
                f"Duplicate maintenance dependency label: {label!r}."
            )
        labels.add(label)
        if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(
            repository
        ):
            raise MaintenancePolicyError(f"{context} has an invalid repository.")
        if source not in {"releases", "tag-channel"}:
            raise MaintenancePolicyError(f"{context} source must be releases or tag-channel.")
        if source == "tag-channel":
            if not isinstance(channel, str) or not CHANNEL_PATTERN.fullmatch(channel):
                raise MaintenancePolicyError(f"{context} requires a safe channel.")
        elif channel is not None:
            raise MaintenancePolicyError(
                f"{context} can set channel only with source tag-channel."
            )
        definitions.append(
            DependencyDefinition(dependency_id, label, repository, source, channel)
        )

    policy = MaintenancePolicy(
        **threshold_values,
        dependencies=tuple(definitions),
    )
    if not (
        policy.dependency_warning_days < policy.dependency_overdue_days
        < policy.review_overdue_days
        < policy.deprecation_days
    ):
        raise MaintenancePolicyError(
            "Maintenance thresholds must increase from warning through deprecation."
        )
    return policy
