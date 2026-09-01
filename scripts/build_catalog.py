#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate catalog metadata and build the static GitHub Pages catalog."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    from scripts.catalog_maintenance_policy import (
        MaintenancePolicy,
        MaintenancePolicyError,
        load_maintenance_policy_file,
    )
    from scripts.example_dependencies import (
        MANIFEST_NAME as DEPENDENCY_MANIFEST_NAME,
        DependencyContract,
        DependencyContractError,
        HARNESS_LABELS,
        ResolvedStack,
        load_dependency_contract,
        resolve_dependency_contract,
    )
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from catalog_maintenance_policy import (  # type: ignore[no-redef]
        MaintenancePolicy,
        MaintenancePolicyError,
        load_maintenance_policy_file,
    )
    from example_dependencies import (  # type: ignore[no-redef]
        MANIFEST_NAME as DEPENDENCY_MANIFEST_NAME,
        DependencyContract,
        DependencyContractError,
        HARNESS_LABELS,
        ResolvedStack,
        load_dependency_contract,
        resolve_dependency_contract,
    )

try:
    import markdown
except ModuleNotFoundError:  # Report a targeted build error when dependencies are absent.
    markdown = None


INDUSTRY_EMOJIS: dict[str, str] = {
    "Academia/Education": "🎓",
    "AEC": "🏗️",
    "Aerospace": "🚀",
    "Agriculture": "🌾",
    "Automotive/Transportation": "🚗",
    "Cloud Services": "☁️",
    "Consumer Internet": "🌐",
    "Energy": "⚡",
    "Financial Services": "💳",
    "Gaming": "🎮",
    "Hardware/Semiconductor": "🖥️",
    "Health and Life Sciences": "🧬",
    "HPC/Scientific Computing": "🔬",
    "Manufacturing": "🏭",
    "Media & Entertainment": "🎬",
    "Public Sector": "🏛️",
    "Restaurant/Quick Service": "🍽️",
    "Retail/Consumer Packaged Goods": "🛍️",
    "Smart Cities/Spaces": "🏙️",
    "Telecommunications": "📡",
    "Other": "✨",
}
INDUSTRIES: tuple[str, ...] = tuple(INDUSTRY_EMOJIS)

HARNESS_PRESENTATION: dict[str, dict[str, str]] = {
    "hermes": {
        "label": HARNESS_LABELS["hermes"],
        "mark": "H",
        "url": "https://github.com/NousResearch/hermes-agent",
    },
    "openclaw": {
        "label": HARNESS_LABELS["openclaw"],
        "mark": "OC",
        "url": "https://github.com/openclaw/openclaw",
    },
}

LIFECYCLES: tuple[str, ...] = ("Active", "Stable", "Deprecated")
MAINTENANCE_STATUSES: dict[str, str] = {
    "current": "Current",
    "review-soon": "Review soon",
    "review-due": "Review due",
    "review-overdue": "Review overdue",
    "deprecated": "Deprecated",
}
MAINTENANCE_POLICY_PATH = Path("scripts/catalog-maintenance.json")
MAINTENANCE_RELEASES_PATH = Path("scripts/catalog-maintenance-releases.json")
MAX_DEPENDENCY_CONSUMER_BYTES = 1_000_000

PAGES_BASE_URL = "https://nvidia.github.io/nemoclaw-community/"
PATH_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MERMAID_VERSION = "11.17.2"
MERMAID_SHA256 = (
    "7a644017d37f93c8359790884e6b67fb1f747c78eb20475952404bd87190a3f8"
)
MERMAID_SRI = "sha256-" + base64.b64encode(
    bytes.fromhex(MERMAID_SHA256)
).decode("ascii")
MERMAID_CACHE_PATH = Path(".cache/catalog/mermaid.tiny.js")
MERMAID_FENCE_OPEN_PATTERN = re.compile(r"^```mermaid[ \t]*\r?$", re.MULTILINE)
MERMAID_FENCE_PATTERN = re.compile(
    r"^```mermaid[ \t]*\r?\n(?P<source>.*?)^```[ \t]*\r?$",
    re.MULTILINE | re.DOTALL,
)
MERMAID_DIAGRAM_TYPES = {
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram-v2",
}
MERMAID_FORBIDDEN_SOURCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"%%\{"), "configuration directives"),
    (
        re.compile(r"(?:^|;)\s*click\b", re.IGNORECASE | re.MULTILINE),
        "click directives",
    ),
    (
        re.compile(
            r"@\{[^}\r\n]*\b(?:icon|img)\s*:",
            re.IGNORECASE,
        ),
        "image or icon shapes",
    ),
    (
        re.compile(
            r"<\s*/?\s*(?:"
            r"a|audio|base|embed|foreignObject|form|iframe|image|img|link|meta|"
            r"object|script|style|video)\b",
            re.IGNORECASE,
        ),
        "active HTML elements",
    ),
    (re.compile(r"@import\b", re.IGNORECASE), "CSS imports"),
    (re.compile(r"url\s*\(", re.IGNORECASE), "CSS URL references"),
)
MAX_MERMAID_DIAGRAMS_PER_README = 10
MAX_MERMAID_SOURCE_SIZE = 10_000
DETAIL_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; font-src 'self'; connect-src 'none'; "
    "object-src 'none'; frame-src 'self'; worker-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)


@dataclass(frozen=True)
class Category:
    """One canonical artifact/provenance category."""

    id: str
    singular: str
    kind: str
    provenance: str | None = None
    readme_path: str = ""
    title: str = ""
    description: str = ""


CATEGORY_DEFINITIONS: tuple[Category, ...] = (
    Category(
        "nvidia-recipes",
        "NVIDIA recipe",
        "recipe",
        "nvidia",
        "examples/recipes/nvidia/README.md",
    ),
    Category(
        "partner-recipes",
        "Partner recipe",
        "recipe",
        "partner",
        "examples/recipes/partners/README.md",
    ),
    Category(
        "community-recipes",
        "Community recipe",
        "recipe",
        "community",
        "examples/recipes/community/README.md",
    ),
    Category(
        "nvidia-field-demos",
        "NVIDIA field demo",
        "demo",
        readme_path="examples/demos/field/README.md",
    ),
    Category(
        "developer-tools",
        "Developer tool",
        "tool",
        readme_path="examples/tools/README.md",
    ),
)

CATEGORY_DEFINITION_BY_ID = {
    category.id: category for category in CATEGORY_DEFINITIONS
}


@dataclass(frozen=True)
class Collection:
    """One cross-cutting recipe collection and its browse presentation."""

    id: str
    browse_id: str
    metadata_value: str
    readme_path: str
    title: str = ""
    description: str = ""


COLLECTION_DEFINITIONS: tuple[Collection, ...] = (
    Collection(
        "hackathon",
        "hackathon-recipes",
        "Hackathon",
        "examples/collections/hackathon/README.md",
    ),
    Collection(
        "build-a-claw",
        "build-a-claw-recipes",
        "Build-a-Claw",
        "examples/collections/build-a-claw/README.md",
    ),
)

COLLECTION_DEFINITION_BY_VALUE = {
    collection.metadata_value: collection for collection in COLLECTION_DEFINITIONS
}


@dataclass(frozen=True)
class MaintenanceRelease:
    """Latest stable upstream release observed by the scheduled catalog build."""

    tag: str
    component_version: str
    published_on: dt.date
    url: str


@dataclass(frozen=True)
class MaintenanceSnapshot:
    """Validated release-feed data used for one deterministic catalog build."""

    checked_at: str
    checked_on: dt.date
    releases: dict[str, MaintenanceRelease]
    nemoclaw_stacks: dict[str, Any]


@dataclass(frozen=True)
class MaintenanceStatus:
    """One example's computed public maintenance signal."""

    id: str
    label: str
    explanation: str
    effective_on: dt.date
    activity_source: str
    as_of: dt.date
    checked_on: dt.date


@dataclass(frozen=True)
class CatalogEntry:
    """Validated README metadata plus taxonomy derived from its path."""

    path: str
    title: str
    description: str
    industry: str
    requirements: str
    lifecycle: str
    reviewed_on: dt.date | None
    dependency_contract: DependencyContract | None
    stack: ResolvedStack | None
    collections: tuple[Collection, ...]
    category: Category
    contributor: str | None = None
    upstream_url: str | None = None
    readme_body: str = ""
    last_content_change_on: dt.date | None = None
    maintenance: MaintenanceStatus | None = None

    @property
    def readme_path(self) -> str:
        return f"examples/{self.path}/README.md"

    @property
    def guide_url(self) -> str:
        return (
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/"
            f"{self.readme_path}"
        )

    @property
    def detail_path(self) -> str:
        return f"examples/{self.path}/index.html"

    @property
    def detail_url(self) -> str:
        return f"examples/{self.path}/"

    @property
    def absolute_detail_url(self) -> str:
        return f"{PAGES_BASE_URL}{self.detail_url}"

    @property
    def id(self) -> str:
        return f"example-{slugify(self.title)}"

    @property
    def industry_id(self) -> str:
        return slugify(self.industry)

    @property
    def industry_emoji(self) -> str:
        return INDUSTRY_EMOJIS[self.industry]

    @property
    def industry_label(self) -> str:
        return f"{self.industry_emoji} {self.industry}"

    @property
    def display_label(self) -> str:
        if self.category.id == "partner-recipes":
            return f"{self.category.singular} · {self.contributor}"
        return self.category.singular

    @property
    def collection_ids(self) -> tuple[str, ...]:
        return tuple(collection.id for collection in self.collections)

    @property
    def dependency_ids(self) -> tuple[str, ...]:
        if self.stack is None:
            return ()
        if self.stack.distribution == "nemoclaw":
            return ("nemoclaw",)
        dependencies = [
            "hermes-agent" if self.stack.harness == "hermes" else "openclaw"
        ]
        if self.stack.openshell_version is not None:
            dependencies.append("openshell")
        return tuple(dependencies)

    @property
    def stack_status(self) -> str:
        if self.stack is not None:
            return "declared"
        return "not-applicable" if self.category.kind == "tool" else "not-declared"

    @property
    def search_text(self) -> str:
        values = (
            self.title,
            self.description,
            self.industry,
            self.requirements,
            self.category.title,
            self.display_label,
            self.contributor or "",
            " ".join(collection.title for collection in self.collections),
            self.lifecycle,
            " ".join(self.dependency_ids),
            self.stack.harness_version if self.stack else "",
            self.stack.openshell_version if self.stack else "",
            self.stack.harness if self.stack else "",
            self.maintenance.label if self.maintenance else "",
        )
        return " ".join(value for value in values if value)


class CatalogError(ValueError):
    """Raised when source metadata or generated output is invalid."""


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one UTF-8 JSON object with a targeted catalog error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"Unable to read {label} from {path}: {error}") from error
    if not isinstance(value, dict):
        raise CatalogError(f"{label} must contain one JSON object: {path}")
    return value


def load_maintenance_policy(root: Path) -> MaintenancePolicy:
    """Load the single global maintenance policy without network access."""

    try:
        return load_maintenance_policy_file(root / MAINTENANCE_POLICY_PATH)
    except MaintenancePolicyError as error:
        raise CatalogError(str(error)) from error


def _parse_iso_date(value: Any, context: str) -> dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CatalogError(f"{context} must use YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise CatalogError(f"{context} must be a real calendar date.") from error


def load_maintenance_snapshot(
    root: Path,
    policy: MaintenancePolicy,
    path: Path | None = None,
) -> MaintenanceSnapshot:
    """Load the latest official release observations for a catalog build."""

    snapshot_path = path or (root / MAINTENANCE_RELEASES_PATH)
    if not snapshot_path.is_absolute():
        snapshot_path = root / snapshot_path
    snapshot_path = snapshot_path.absolute()
    if (
        snapshot_path.is_symlink()
        or not snapshot_path.is_file()
        or not snapshot_path.resolve().is_relative_to(root.resolve())
    ):
        raise CatalogError(
            f"Maintenance release snapshot must be a regular file inside the repository: "
            f"{snapshot_path}"
        )
    value = _read_json_object(snapshot_path, "catalog maintenance release snapshot")
    if value.get("schema_version") != 1:
        raise CatalogError("Maintenance release snapshot schema_version must be 1.")
    checked_at = value.get("checked_at")
    if not isinstance(checked_at, str):
        raise CatalogError("Maintenance release snapshot checked_at must be an ISO timestamp.")
    try:
        parsed_checked_at = dt.datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise CatalogError(
            "Maintenance release snapshot checked_at must be an ISO timestamp."
        ) from error
    if parsed_checked_at.tzinfo is None:
        raise CatalogError("Maintenance release snapshot checked_at requires a timezone.")
    releases_value = value.get("releases")
    nemoclaw_stacks = value.get("nemoclaw_stacks")
    if not isinstance(releases_value, dict):
        raise CatalogError("Maintenance release snapshot requires a releases object.")
    if not isinstance(nemoclaw_stacks, dict):
        raise CatalogError(
            "Maintenance release snapshot requires a nemoclaw_stacks object."
        )

    expected_ids = set(policy.dependencies_by_id)
    if set(releases_value) != expected_ids:
        missing = sorted(expected_ids - set(releases_value))
        unknown = sorted(set(releases_value) - expected_ids)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise CatalogError(
            "Maintenance release snapshot does not match the policy registry: "
            + "; ".join(details)
            + "."
        )

    releases: dict[str, MaintenanceRelease] = {}
    for dependency_id in sorted(expected_ids):
        record = releases_value[dependency_id]
        if not isinstance(record, dict):
            raise CatalogError(
                f"Maintenance release {dependency_id!r} must be an object."
            )
        if set(record) != {"tag", "component_version", "published_on", "url"}:
            raise CatalogError(
                f"Maintenance release {dependency_id!r} has invalid fields."
            )
        definition = policy.dependencies_by_id[dependency_id]
        tag = record.get("tag")
        component_version = record.get("component_version")
        url = record.get("url")
        if (
            not isinstance(tag, str)
            or not tag
            or len(tag) > 100
            or any(ord(character) < 32 for character in tag)
        ):
            raise CatalogError(
                f"Maintenance release {dependency_id!r} has an invalid tag."
            )
        if (
            not isinstance(component_version, str)
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", component_version) is None
        ):
            raise CatalogError(
                f"Maintenance release {dependency_id!r} has an invalid component_version."
            )
        if not isinstance(url, str) or not url.startswith(
            f"https://github.com/{definition.repository}/"
        ):
            raise CatalogError(
                f"Maintenance release {dependency_id!r} must link to its GitHub repository."
            )
        published_on = _parse_iso_date(
            record.get("published_on"),
            f"Maintenance release {dependency_id!r} published_on",
        )
        if published_on > parsed_checked_at.astimezone(dt.timezone.utc).date():
            raise CatalogError(
                f"Maintenance release {dependency_id!r} cannot be newer than checked_at."
            )
        releases[dependency_id] = MaintenanceRelease(
            tag=tag,
            component_version=component_version,
            published_on=published_on,
            url=url,
        )
    return MaintenanceSnapshot(
        checked_at=checked_at,
        checked_on=parsed_checked_at.astimezone(dt.timezone.utc).date(),
        releases=releases,
        nemoclaw_stacks=nemoclaw_stacks,
    )


def catalog_as_of_date(value: str | None = None) -> dt.date:
    """Return the UTC date used for age thresholds, with a testable override."""

    configured = value or os.environ.get("CATALOG_AS_OF_DATE")
    if configured:
        return _parse_iso_date(configured, "Catalog as-of date")
    return dt.datetime.now(dt.timezone.utc).date()


def slugify(value: str) -> str:
    """Return the stable lowercase URL identifier used by the catalog UI."""

    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def path_uses_symlink(root: Path, path: Path) -> bool:
    """Return whether a repository-relative path contains any symlink."""

    root_absolute = root.absolute()
    path_absolute = path.absolute()
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError:
        return True
    current = root_absolute
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def is_regular_repo_file(root: Path, path: Path) -> bool:
    """Return whether path is a regular file contained in root without symlinks."""

    return (
        not path_uses_symlink(root, path)
        and path.is_file()
        and path.resolve().is_relative_to(root.resolve())
    )


def classify_path(
    path: str,
    categories_by_id: dict[str, Category] | None = None,
) -> Category:
    """Derive artifact kind and recipe provenance from canonical placement."""

    parts = PurePosixPath(path).parts
    category_id: str | None = None
    if len(parts) == 3 and parts[:2] == ("recipes", "nvidia"):
        category_id = "nvidia-recipes"
    elif len(parts) == 3 and parts[:2] == ("recipes", "community"):
        category_id = "community-recipes"
    elif len(parts) == 4 and parts[:2] == ("recipes", "partners"):
        category_id = "partner-recipes"
    elif len(parts) == 3 and parts[:2] == ("demos", "field"):
        category_id = "nvidia-field-demos"
    elif len(parts) == 2 and parts[0] == "tools":
        category_id = "developer-tools"

    if category_id is None or any(
        PATH_SEGMENT_PATTERN.fullmatch(part) is None for part in parts
    ):
        raise CatalogError(
            f"Catalog path does not match the canonical example taxonomy: {path!r}"
        )
    return (categories_by_id or CATEGORY_DEFINITION_BY_ID)[category_id]


def discover_example_paths(
    root: Path,
    categories_by_id: dict[str, Category] | None = None,
) -> set[str]:
    """Discover canonical example directories and require one safe root README."""

    examples = root / "examples"
    if not examples.is_dir() or examples.is_symlink():
        raise CatalogError("examples/ must be a regular directory.")
    allowed_roots = {"collections", "demos", "recipes", "tools"}
    unexpected_roots = {
        child.name
        for child in examples.iterdir()
        if child.is_dir() and child.name not in allowed_roots
    }
    if unexpected_roots:
        raise CatalogError(
            "Unexpected example taxonomy directories: "
            + ", ".join(sorted(unexpected_roots))
        )

    recipes = examples / "recipes"
    if recipes.is_dir():
        allowed_recipe_roots = {"community", "nvidia", "partners"}
        unexpected_recipe_roots = {
            child.name
            for child in recipes.iterdir()
            if child.is_dir() and child.name not in allowed_recipe_roots
        }
        if unexpected_recipe_roots:
            raise CatalogError(
                "Unexpected recipe provenance directories: "
                + ", ".join(sorted(unexpected_recipe_roots))
            )

    demos = examples / "demos"
    if demos.is_dir():
        unexpected_demo_roots = {
            child.name
            for child in demos.iterdir()
            if child.is_dir() and child.name != "field"
        }
        if unexpected_demo_roots:
            raise CatalogError(
                "Unexpected demo taxonomy directories: "
                + ", ".join(sorted(unexpected_demo_roots))
            )

    collections = examples / "collections"
    if collections.is_dir():
        expected_collection_roots = {
            PurePosixPath(collection.readme_path).parent.name
            for collection in COLLECTION_DEFINITIONS
        }
        unexpected_collection_roots = {
            child.name
            for child in collections.iterdir()
            if child.is_dir() and child.name not in expected_collection_roots
        }
        if unexpected_collection_roots:
            raise CatalogError(
                "Unexpected recipe collection directories: "
                + ", ".join(sorted(unexpected_collection_roots))
            )
        for collection_root in expected_collection_roots:
            index = collections / collection_root
            if not index.is_dir():
                continue
            unexpected_entries = sorted(
                child.name for child in index.iterdir() if child.name != "README.md"
            )
            if unexpected_entries:
                raise CatalogError(
                    "Recipe collection directories may contain only README.md: "
                    + ", ".join(
                        f"examples/collections/{collection_root}/{name}"
                        for name in unexpected_entries
                    )
                )

    patterns = (
        "recipes/nvidia/*",
        "recipes/community/*",
        "recipes/partners/*/*",
        "demos/field/*",
        "tools/*",
    )
    paths: set[str] = set()
    for pattern in patterns:
        for directory in examples.glob(pattern):
            if not directory.is_dir():
                continue
            path = directory.relative_to(examples).as_posix()
            classify_path(path, categories_by_id)
            if path_uses_symlink(examples, directory):
                raise CatalogError(
                    f"Example directory must not be a symlink: examples/{path}"
                )
            if not directory.resolve().is_relative_to(examples.resolve()):
                raise CatalogError(
                    f"Example directory resolves outside examples/: examples/{path}"
                )
            readme = directory / "README.md"
            if not is_regular_repo_file(examples, readme):
                raise CatalogError(
                    f"Example directory requires a regular README.md: examples/{path}"
                )
            paths.add(path)
    return paths


CATALOG_TABLE_HEADER = "| Catalog field | Value |"
CATALOG_TABLE_DIVIDER = "| --- | --- |"
CATALOG_METADATA_HEADING = "## Catalog Metadata"
CATALOG_FIELD_ORDER = (
    "Description",
    "Industry",
    "Requirements",
    "Lifecycle",
    "Reviewed",
    "Upstream",
    "Contributor",
    "Collection",
)
EXAMPLES_HEADING = "## Examples"


def _skip_leading_readme_comments(lines: list[str], readme_path: str) -> int:
    """Skip optional legacy YAML plus comments before the visible README title."""

    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index] == "---":
        index += 1
        while index < len(lines) and lines[index] != "---":
            index += 1
        if index >= len(lines):
            raise CatalogError(f"Unclosed leading YAML block in {readme_path}.")
        index += 1
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines) or not lines[index].lstrip().startswith("<!--"):
            break
        while index < len(lines) and "-->" not in lines[index]:
            index += 1
        if index >= len(lines):
            raise CatalogError(f"Unclosed leading HTML comment in {readme_path}.")
        index += 1
    return index


def _parse_discovery_readme(
    root: Path,
    definition: Category | Collection,
) -> tuple[str, str]:
    """Read one browse-group title and description from its index README."""

    readme_path = definition.readme_path
    readme = root / readme_path
    if not is_regular_repo_file(root, readme):
        raise CatalogError(f"Browse group requires a regular README.md: {readme_path}")
    lines = readme.read_text(encoding="utf-8").splitlines()
    index = _skip_leading_readme_comments(lines, readme_path)
    if index >= len(lines):
        raise CatalogError(f"Browse-group README is empty: {readme_path}")
    title_match = re.fullmatch(r"# ([^#].*)", lines[index])
    if title_match is None:
        raise CatalogError(
            f"Browse-group README must begin with one level-one title: {readme_path}"
        )
    title = title_match.group(1).strip()
    if title != title_match.group(1) or len(title) > 100:
        raise CatalogError(
            f"Browse-group title must be trimmed and at most 100 characters: {readme_path}"
        )
    if any(ord(character) < 32 for character in title) or re.search(
        r"[`*_~\[\]<>]", title
    ):
        raise CatalogError(f"Browse-group title must be plain text: {readme_path}")
    expected_id = (
        definition.id if isinstance(definition, Category) else definition.browse_id
    )
    if slugify(title) != expected_id:
        raise CatalogError(
            f"Browse-group title must slugify to {expected_id!r}: {readme_path}"
        )

    index += 1
    if index >= len(lines) or lines[index].strip():
        raise CatalogError(
            f"Browse-group title must be followed by a blank line: {readme_path}"
        )
    index += 1
    description_lines: list[str] = []
    while index < len(lines) and lines[index].strip():
        description_lines.append(lines[index].strip())
        index += 1
    description = " ".join(description_lines)
    if not description:
        raise CatalogError(f"Browse-group description is required: {readme_path}")
    if len(description) > 300:
        raise CatalogError(
            f"Browse-group description must be at most 300 characters: {readme_path}"
        )
    if any(ord(character) < 32 for character in description) or re.search(
        r"[`*_~\[\]<>]", description
    ) or any(
        re.match(r"(?:#{1,6}|>|[-+]|\d+[.)])(?:\s|$)|-{3,}$", line)
        for line in description_lines
    ):
        raise CatalogError(
            f"Browse-group description must be plain text: {readme_path}"
        )
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or lines[index] != EXAMPLES_HEADING:
        raise CatalogError(
            f"Browse-group README requires {EXAMPLES_HEADING!r} after its "
            f"description: {readme_path}"
        )
    return title, description


def load_discovery_groups(
    root: Path,
) -> tuple[tuple[Category, ...], tuple[Collection, ...]]:
    """Load authored browse-group presentation from canonical README indexes."""

    categories: list[Category] = []
    for definition in CATEGORY_DEFINITIONS:
        title, description = _parse_discovery_readme(root, definition)
        categories.append(replace(definition, title=title, description=description))
    collections: list[Collection] = []
    for definition in COLLECTION_DEFINITIONS:
        title, description = _parse_discovery_readme(root, definition)
        collections.append(replace(definition, title=title, description=description))
    return tuple(categories), tuple(collections)


def _parse_catalog_row(line: str, readme_path: str) -> tuple[str, str]:
    match = re.fullmatch(r"\| ([A-Za-z]+) \| ([^|]+) \|", line)
    if match is None:
        raise CatalogError(
            f"Invalid catalog metadata row in {readme_path}: {line!r}. "
            "Use `| Field | Value |` with no additional columns."
        )
    field, value = match.groups()
    if field not in CATALOG_FIELD_ORDER:
        raise CatalogError(
            f"Unknown catalog metadata field in {readme_path}: {field!r}."
        )
    if value != value.strip() or not value.strip():
        raise CatalogError(
            f"Catalog metadata field {field!r} must have a trimmed value in "
            f"{readme_path}."
        )
    if any(ord(character) < 32 for character in value) or (
        field != "Upstream" and re.search(r"[`*_~\[\]<>]", value)
    ):
        raise CatalogError(
            f"Catalog metadata field {field!r} must be plain text in {readme_path}."
        )
    return field, value


def _validate_upstream_url(value: str, readme_path: str) -> str:
    """Require a safe absolute HTTPS URL for an optional upstream project."""

    if (
        len(value) > 2048
        or any(character.isspace() for character in value)
        or any(character in "<>" for character in value)
    ):
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL in {readme_path}."
        )
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL in {readme_path}."
        ) from error
    if (
        parts.scheme != "https"
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL without credentials in {readme_path}."
        )
    return value


def _dependency_contract_has_consumer(root: Path, example_root: Path) -> bool:
    """Return whether implementation code consumes the root dependency contract."""

    for candidate in example_root.rglob("*.sh"):
        relative = candidate.relative_to(example_root)
        if (
            any(part in {"test", "tests"} for part in relative.parts)
            or not is_regular_repo_file(root, candidate)
            or candidate.stat().st_size > MAX_DEPENDENCY_CONSUMER_BYTES
        ):
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        implementation = "\n".join(
            line
            for line in content.splitlines()
            if not line.lstrip().startswith("#")
        )
        if (
            "example_dependencies.sh" in implementation
            and re.search(r"(?m)^\s*(?:source|\.)\s+", implementation)
            and re.search(
                r"(?m)^\s*load_example_dependencies(?:\s|$)", implementation
            )
        ):
            return True
    return False


def load_example_dependency_contract(
    root: Path, path: str
) -> DependencyContract | None:
    """Load one dependency contract that controls example implementation."""

    example_root = root / "examples" / path
    manifest_path = example_root / DEPENDENCY_MANIFEST_NAME
    if not manifest_path.exists():
        return None
    if not is_regular_repo_file(root, manifest_path):
        raise CatalogError(
            f"Dependency contract must be a regular file: "
            f"examples/{path}/{DEPENDENCY_MANIFEST_NAME}."
        )
    try:
        contract = load_dependency_contract(manifest_path)
    except DependencyContractError as error:
        raise CatalogError(str(error)) from error
    if not _dependency_contract_has_consumer(root, example_root):
        raise CatalogError(
            f"Dependency contract {manifest_path} is catalog-only; an implementation "
            "file must consume it through the shared dependency loader."
        )
    return contract


def parse_readme_metadata(
    root: Path,
    path: str,
    categories_by_id: dict[str, Category] | None = None,
    collections_by_value: dict[str, Collection] | None = None,
) -> CatalogEntry:
    """Parse the required human-readable metadata block from one example README."""

    category = classify_path(path, categories_by_id)
    readme_path = f"examples/{path}/README.md"
    readme = root / readme_path
    if not is_regular_repo_file(root, readme):
        raise CatalogError(f"Example README is not a regular file: {readme_path}")
    lines = readme.read_text(encoding="utf-8").splitlines()
    index = _skip_leading_readme_comments(lines, readme_path)

    if index >= len(lines):
        raise CatalogError(f"Example README is empty: {readme_path}")
    title_match = re.fullmatch(r"# ([^#].*)", lines[index])
    if title_match is None:
        raise CatalogError(
            f"The first README content must be one level-one title in {readme_path}."
        )
    title = title_match.group(1).strip()
    if title != title_match.group(1) or len(title) > 100:
        raise CatalogError(
            f"README title must be trimmed and at most 100 characters in {readme_path}."
        )
    if any(ord(character) < 32 for character in title) or re.search(
        r"[`*_~\[\]<>]", title
    ):
        raise CatalogError(f"README title must be plain text in {readme_path}.")
    if not slugify(title):
        raise CatalogError(f"README title must contain letters or numbers in {readme_path}.")
    index += 1
    if index >= len(lines) or lines[index].strip():
        raise CatalogError(f"README title must be followed by a blank line in {readme_path}.")
    body_start = index + 1
    table_indices = [
        line_index
        for line_index in range(body_start, len(lines))
        if lines[line_index] == CATALOG_TABLE_HEADER
    ]
    if not table_indices:
        raise CatalogError(
            f"README requires `{CATALOG_TABLE_HEADER}` after the title or in a "
            f"final `{CATALOG_METADATA_HEADING}` section in {readme_path}."
        )
    if len(table_indices) > 1:
        raise CatalogError(f"Duplicate catalog metadata tables in {readme_path}.")
    table_index = table_indices[0]
    metadata_heading_index: int | None = None
    if table_index != body_start:
        metadata_heading_index = table_index - 2
        if (
            metadata_heading_index < body_start
            or lines[metadata_heading_index] != CATALOG_METADATA_HEADING
            or lines[metadata_heading_index + 1].strip()
        ):
            raise CatalogError(
                f"Catalog metadata must follow the README title or appear in a "
                f"final `{CATALOG_METADATA_HEADING}` section in {readme_path}."
            )
    index = table_index + 1
    if index >= len(lines) or lines[index] != CATALOG_TABLE_DIVIDER:
        raise CatalogError(
            f"README catalog table must use `{CATALOG_TABLE_DIVIDER}` in {readme_path}."
        )
    index += 1

    fields: dict[str, str] = {}
    field_names: list[str] = []
    while index < len(lines) and lines[index].startswith("|"):
        field, value = _parse_catalog_row(lines[index], readme_path)
        if field in fields:
            raise CatalogError(
                f"Duplicate catalog metadata field {field!r} in {readme_path}."
            )
        fields[field] = value
        field_names.append(field)
        index += 1
    expected_order = sorted(field_names, key=CATALOG_FIELD_ORDER.index)
    if field_names != expected_order:
        raise CatalogError(
            f"Catalog metadata fields are out of order in {readme_path}; use: "
            + ", ".join(CATALOG_FIELD_ORDER)
            + "."
        )
    missing_fields = {"Description", "Industry", "Requirements"} - set(fields)
    if missing_fields:
        raise CatalogError(
            f"Missing catalog metadata fields in {readme_path}: "
            + ", ".join(sorted(missing_fields))
        )
    if index < len(lines) and lines[index].strip():
        raise CatalogError(
            f"README catalog metadata table must be followed by a blank line in "
            f"{readme_path}."
        )
    if metadata_heading_index is not None and any(
        line.strip() for line in lines[index:]
    ):
        raise CatalogError(
            f"`{CATALOG_METADATA_HEADING}` must be the final README section in "
            f"{readme_path}."
        )
    while index < len(lines) and not lines[index].strip():
        index += 1

    if metadata_heading_index is None:
        readme_body = "\n".join(lines[index:]).strip()
    else:
        readme_body = "\n".join(lines[body_start:metadata_heading_index]).strip()

    description = fields["Description"]
    if len(description) > 300:
        raise CatalogError(
            f"Description must be at most 300 characters in {readme_path}."
        )
    industry_value = fields["Industry"]
    industry = next(
        (
            name
            for name, emoji in INDUSTRY_EMOJIS.items()
            if industry_value == f"{emoji} {name}"
        ),
        None,
    )
    if industry is None:
        raise CatalogError(
            f"Industry must use one documented emoji and title in {readme_path}; "
            f"got {industry_value!r}."
        )
    requirements = fields["Requirements"]
    if len(requirements) > 240:
        raise CatalogError(
            f"Requirements must be at most 240 characters in {readme_path}."
        )

    lifecycle = fields.get("Lifecycle", "Active")
    if lifecycle not in LIFECYCLES:
        raise CatalogError(
            f"Lifecycle must be one of {', '.join(LIFECYCLES)} in {readme_path}; "
            f"got {lifecycle!r}."
        )

    reviewed_value = fields.get("Reviewed")
    reviewed_on = (
        _parse_iso_date(reviewed_value, f"Reviewed in {readme_path}")
        if reviewed_value is not None
        else None
    )

    # The root dependency contract is both an installer input and the catalog's
    # compatibility source. Keeping those concerns on one file prevents display
    # metadata from drifting away from what an example actually runs.
    dependency_contract = load_example_dependency_contract(root, path)

    upstream_url = fields.get("Upstream")
    if upstream_url is not None:
        upstream_url = _validate_upstream_url(upstream_url, readme_path)

    contributor = fields.get("Contributor")
    if contributor is not None and len(contributor) > 100:
        raise CatalogError(
            f"Contributor must be at most 100 characters in {readme_path}."
        )
    if category.id == "partner-recipes" and contributor is None:
        raise CatalogError(f"Partner recipe {path!r} requires a Contributor row.")
    if category.id != "partner-recipes" and contributor is not None:
        raise CatalogError(f"Only partner recipes can set Contributor ({path!r}).")

    collection_value = fields.get("Collection")
    collection_definitions = (
        collections_by_value or COLLECTION_DEFINITION_BY_VALUE
    )
    if collection_value is None:
        collections: tuple[Collection, ...] = ()
    elif collection_value in collection_definitions and category.kind == "recipe":
        collections = (collection_definitions[collection_value],)
    elif collection_value in collection_definitions:
        raise CatalogError("Only recipes can join a recipe collection.")
    else:
        raise CatalogError(
            f"Unknown Collection value in {readme_path}: {collection_value!r}."
        )

    return CatalogEntry(
        path=path,
        title=title,
        description=description,
        industry=industry,
        requirements=requirements,
        lifecycle=lifecycle,
        reviewed_on=reviewed_on,
        dependency_contract=dependency_contract,
        stack=None,
        collections=collections,
        category=category,
        contributor=contributor,
        upstream_url=upstream_url,
        readme_body=readme_body,
    )


def load_catalog(
    root: Path,
    categories: tuple[Category, ...] | None = None,
    collections: tuple[Collection, ...] | None = None,
) -> list[CatalogEntry]:
    """Discover examples and validate catalog metadata in their READMEs."""

    if categories is None or collections is None:
        loaded_categories, loaded_collections = load_discovery_groups(root)
        categories = categories or loaded_categories
        collections = collections or loaded_collections
    categories_by_id = {category.id: category for category in categories}
    collections_by_value = {
        collection.metadata_value: collection for collection in collections
    }
    paths = discover_example_paths(root, categories_by_id)
    if not paths:
        raise CatalogError("No canonical example READMEs were discovered.")
    entries = [
        parse_readme_metadata(
            root,
            path,
            categories_by_id,
            collections_by_value,
        )
        for path in paths
    ]
    category_order = {
        category.id: index for index, category in enumerate(categories)
    }
    def sort_key(entry: CatalogEntry) -> tuple[int, str, str, str]:
        qualifier = ""
        if entry.category.id == "partner-recipes":
            qualifier = (entry.contributor or "").casefold()
        return (
            category_order[entry.category.id],
            qualifier,
            entry.title.casefold(),
            entry.path,
        )

    entries.sort(key=sort_key)

    seen_titles: set[str] = set()
    seen_ids: set[str] = set()
    for entry in entries:
        if entry.title.casefold() in seen_titles:
            raise CatalogError(f"Duplicate catalog title: {entry.title}")
        if entry.id in seen_ids:
            raise CatalogError(f"Duplicate generated catalog ID: {entry.id}")
        seen_titles.add(entry.title.casefold())
        seen_ids.add(entry.id)
    return entries


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    allow_failure: bool = False,
) -> str | None:
    """Run Git without a shell and return text, optionally treating failure as absent."""

    result = subprocess.run(
        ["git", "--literal-pathspecs", *arguments],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        if allow_failure:
            return None
        detail = result.stderr.strip() or "unknown Git error"
        raise CatalogError(f"Unable to inspect example history: {detail}")
    return result.stdout


def last_content_change_on(
    root: Path,
    entry: CatalogEntry,
    as_of: dt.date,
) -> dt.date:
    """Find the latest committed change anywhere in an example directory."""

    inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"], allow_failure=True)
    if inside is None or inside.strip() != "true":
        raise CatalogError("Catalog maintenance status requires a Git worktree.")
    shallow = _run_git(root, ["rev-parse", "--is-shallow-repository"])
    if shallow is None or shallow.strip() != "false":
        raise CatalogError(
            "Catalog maintenance status requires full Git history; check out with "
            "fetch-depth: 0."
        )
    timestamp = _run_git(
        root,
        ["log", "-1", "--format=%cI", "--", f"examples/{entry.path}"],
    )
    if timestamp is None or not timestamp.strip():
        raise CatalogError(f"No committed history was found for {entry.readme_path}.")
    try:
        changed_at = dt.datetime.fromisoformat(timestamp.strip()).astimezone(
            dt.timezone.utc
        ).date()
    except ValueError as error:
        raise CatalogError(
            f"Unable to parse Git history for {entry.readme_path}."
        ) from error
    if changed_at > as_of:
        raise CatalogError(
            f"Last content change for {entry.readme_path} is after the "
            f"catalog as-of date {as_of.isoformat()}."
        )
    return changed_at


def _maintenance_status_for_entry(
    entry: CatalogEntry,
    policy: MaintenancePolicy,
    snapshot: MaintenanceSnapshot,
    as_of: dt.date,
) -> MaintenanceStatus:
    if entry.last_content_change_on is None:
        raise CatalogError(f"Missing content history for {entry.readme_path}.")
    if entry.reviewed_on is not None and entry.reviewed_on > as_of:
        raise CatalogError(
            f"Reviewed date in {entry.readme_path} cannot be after {as_of.isoformat()}."
        )
    if snapshot.checked_on > as_of:
        raise CatalogError(
            "Maintenance release snapshot cannot be newer than the catalog as-of date."
        )

    if entry.reviewed_on is not None and entry.reviewed_on > entry.last_content_change_on:
        effective_on = entry.reviewed_on
        activity_source = "maintenance review"
    else:
        effective_on = entry.last_content_change_on
        activity_source = "committed example change"
    age_days = (as_of - effective_on).days

    def version_tuple(value: str) -> tuple[int, ...]:
        parts = tuple(int(part) for part in value.removeprefix("v").split("."))
        return parts + (0,) * (4 - len(parts))

    dependency_updates: list[str] = []
    update_labels: dict[str, str] = {}
    if entry.stack is not None:
        if entry.stack.distribution == "nemoclaw":
            assert entry.dependency_contract is not None
            assert entry.stack.distribution_version is not None
            nemoclaw_release = snapshot.releases["nemoclaw"]
            if (
                version_tuple(entry.stack.distribution_version)
                < version_tuple(nemoclaw_release.tag)
            ):
                try:
                    current_lkg_stack = resolve_dependency_contract(
                        replace(entry.dependency_contract, version=nemoclaw_release.tag),
                        {"nemoclaw_stacks": snapshot.nemoclaw_stacks},
                    )
                except DependencyContractError as error:
                    raise CatalogError(str(error)) from error
                changed_components: list[str] = []
                if entry.stack.harness_version != current_lkg_stack.harness_version:
                    changed_components.append(entry.stack.harness_label)
                if (
                    entry.stack.openshell_version
                    != current_lkg_stack.openshell_version
                ):
                    changed_components.append("OpenShell")
                if changed_components and nemoclaw_release.published_on >= effective_on:
                    dependency_updates.append("nemoclaw")
                    update_labels["nemoclaw"] = " / ".join(changed_components)
        else:
            agent_id = (
                "hermes-agent" if entry.stack.harness == "hermes" else "openclaw"
            )
            agent_release = snapshot.releases[agent_id]
            if (
                version_tuple(entry.stack.harness_version)
                < version_tuple(agent_release.component_version)
                and agent_release.published_on >= effective_on
            ):
                dependency_updates.append(agent_id)
                update_labels[agent_id] = entry.stack.harness_label
            if entry.stack.openshell_version is not None:
                openshell_release = snapshot.releases["openshell"]
                if (
                    version_tuple(entry.stack.openshell_version)
                    < version_tuple(openshell_release.component_version)
                    and openshell_release.published_on >= effective_on
                ):
                    dependency_updates.append("openshell")
                    update_labels["openshell"] = "OpenShell"
    dependency_age_days = {
        dependency_id: (as_of - snapshot.releases[dependency_id].published_on).days
        for dependency_id in dependency_updates
    }

    def dependency_labels(minimum_age: int = 0) -> tuple[str, ...]:
        return tuple(
            update_labels.get(
                dependency_id, policy.dependencies_by_id[dependency_id].label
            )
            for dependency_id in dependency_updates
            if dependency_age_days[dependency_id] >= minimum_age
        )

    available_labels = dependency_labels()
    due_labels = dependency_labels(policy.dependency_warning_days)
    overdue_labels = dependency_labels(policy.dependency_overdue_days)

    def named_releases(labels: tuple[str, ...]) -> tuple[str, str]:
        return ", ".join(labels), "has" if len(labels) == 1 else "have"

    def status(status_id: str, explanation: str) -> MaintenanceStatus:
        return MaintenanceStatus(
            id=status_id,
            label=MAINTENANCE_STATUSES[status_id],
            explanation=explanation,
            effective_on=effective_on,
            activity_source=activity_source,
            as_of=as_of,
            checked_on=snapshot.checked_on,
        )

    if entry.lifecycle == "Deprecated":
        return status(
            "deprecated",
            (
                "This example is retained for reference and is hidden from default "
                "catalog results."
            ),
        )

    if age_days >= policy.deprecation_days:
        return status(
            "deprecated",
            (
                f"Automatically deprecated after {age_days} days without committed "
                "maintenance or a focused review; hidden from default catalog results."
            ),
        )

    activity_overdue = age_days >= policy.review_overdue_days
    if activity_overdue or overdue_labels:
        if overdue_labels and activity_overdue:
            dependency_names, dependency_verb = named_releases(overdue_labels)
            explanation = (
                f"Maintenance review is overdue: activity was {age_days} days ago, and "
                f"{dependency_names} {dependency_verb} exceeded the "
                f"{policy.dependency_overdue_days}-day dependency review window."
            )
        elif overdue_labels:
            dependency_names, dependency_verb = named_releases(overdue_labels)
            explanation = (
                f"Update review is overdue: {dependency_names} {dependency_verb} "
                f"exceeded the {policy.dependency_overdue_days}-day dependency "
                "review window."
            )
        else:
            explanation = (
                f"Maintenance review is overdue because the latest maintenance activity "
                f"was {age_days} days ago."
            )
        return status("review-overdue", explanation)

    if due_labels:
        dependency_names, dependency_verb = named_releases(due_labels)
        return status(
            "review-due",
            (
                f"Update review is due: {dependency_names} {dependency_verb} been "
                f"available for at least {policy.dependency_warning_days} days."
            ),
        )

    if available_labels:
        dependency_names = ", ".join(available_labels)
        update_noun = "A tracked update" if len(available_labels) == 1 else "Tracked updates"
        update_verb = "is" if len(available_labels) == 1 else "are"
        return status(
            "review-soon",
            (
                f"Review soon: {update_noun.lower()} from {dependency_names} {update_verb} "
                f"inside the {policy.dependency_warning_days}-day review window."
            ),
        )

    if entry.lifecycle == "Stable":
        explanation = (
            "This stable example is within its maintenance interval, with no tracked "
            "dependency update detected."
        )
    elif entry.dependency_ids:
        explanation = "No tracked platform dependency update was detected."
    else:
        explanation = "This example is within its periodic maintenance interval."
    return status("current", explanation)


def enrich_catalog_maintenance(
    root: Path,
    entries: list[CatalogEntry],
    policy: MaintenancePolicy,
    snapshot: MaintenanceSnapshot,
    as_of: dt.date,
) -> list[CatalogEntry]:
    """Attach deterministic Git activity and computed maintenance status."""

    enriched: list[CatalogEntry] = []
    for entry in entries:
        try:
            stack = (
                resolve_dependency_contract(
                    entry.dependency_contract,
                    {"nemoclaw_stacks": snapshot.nemoclaw_stacks},
                )
                if entry.dependency_contract is not None
                else None
            )
        except DependencyContractError as error:
            raise CatalogError(str(error)) from error
        with_history = replace(
            entry,
            stack=stack,
            last_content_change_on=last_content_change_on(root, entry, as_of),
        )
        enriched.append(
            replace(
                with_history,
                maintenance=_maintenance_status_for_entry(
                    with_history, policy, snapshot, as_of
                ),
            )
        )
    return enriched


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def group_entries(
    entries: Iterable[CatalogEntry],
    categories: Iterable[Category],
) -> dict[str, list[CatalogEntry]]:
    grouped = {category.id: [] for category in categories}
    for entry in entries:
        grouped[entry.category.id].append(entry)
    return grouped


def entries_for_collection(
    entries: Iterable[CatalogEntry],
    collection: Collection,
) -> list[CatalogEntry]:
    return [
        entry for entry in entries if collection.id in entry.collection_ids
    ]


def _render_markdown_entries(
    entries: list[CatalogEntry],
    relative_to: PurePosixPath,
    *,
    show_category: bool = False,
    show_contributor: bool = False,
) -> list[str]:
    if not entries:
        return ["_No examples are currently in this group._"]
    headers = ["Example"]
    if show_category:
        headers.append("Category")
    if show_contributor:
        headers.append("Contributor")
    headers.extend(("Industry", "Description"))
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for entry in entries:
        relative_readme = posixpath.relpath(entry.readme_path, relative_to.as_posix())
        cells = [f"[{_markdown_cell(entry.title)}]({relative_readme})"]
        if show_category:
            cells.append(_markdown_cell(entry.category.title))
        if show_contributor:
            cells.append(_markdown_cell(entry.contributor or ""))
        cells.extend(
            (
                _markdown_cell(entry.industry_label),
                _markdown_cell(entry.description),
            )
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_discovery_readmes(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> dict[str, str]:
    """Render the generated membership list in every browse-group README."""

    grouped = group_entries(entries, categories)
    rendered: dict[str, str] = {}
    groups: tuple[Category | Collection, ...] = (*categories, *collections)
    for group in groups:
        if isinstance(group, Category):
            members = grouped[group.id]
            show_category = False
            show_contributor = group.id == "partner-recipes"
        else:
            members = entries_for_collection(entries, group)
            show_category = True
            show_contributor = False
        lines = [
            "<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->",
            "<!-- SPDX-License-Identifier: Apache-2.0 -->",
            "",
            f"# {group.title}",
            "",
            group.description,
            "",
            EXAMPLES_HEADING,
            "",
            *_render_markdown_entries(
                members,
                PurePosixPath(group.readme_path).parent,
                show_category=show_category,
                show_contributor=show_contributor,
            ),
            "",
        ]
        rendered[group.readme_path] = "\n".join(lines)
    return rendered


def render_readme(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    """Render the human-readable source catalog from canonical metadata."""

    grouped = group_entries(entries, categories)
    lines = [
        "<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->",
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "",
        "# NemoClaw Community Example Catalog",
        "",
        "Examples are organized first by artifact type. Reusable recipes are organized",
        "again by contributor provenance. Industry is an independent discovery field.",
        "This file is generated from the catalog metadata table in each",
        "example README. Edit that README, then run",
        "`python3 scripts/build_catalog.py --write` from the repository root.",
        "",
    ]
    for category in categories:
        category_entries = grouped[category.id]
        category_link = posixpath.relpath(category.readme_path, "examples")
        lines.extend(
            (
                f"## [{category.title}]({category_link})",
                "",
                category.description,
                "",
                *_render_markdown_entries(
                    category_entries,
                    PurePosixPath("examples"),
                    show_contributor=category.id == "partner-recipes",
                ),
                "",
            )
        )

    lines.extend(("## Recipe Collections", ""))
    for collection in collections:
        collection_link = posixpath.relpath(collection.readme_path, "examples")
        lines.extend(
            (
                f"### [{collection.title}]({collection_link})",
                "",
                collection.description,
                "",
                *_render_markdown_entries(
                    entries_for_collection(entries, collection),
                    PurePosixPath("examples"),
                    show_category=True,
                ),
                "",
            )
        )

    lines.extend(
        (
            "## Contributing An Example",
            "",
            "Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical",
            "[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).",
            "Examples must remain independently deployable and must document their",
            "prerequisites, credentials, policies, startup behavior, verification, and",
            "teardown behavior. Add structured catalog metadata as described in the",
            "[contributor guide](../CONTRIBUTING.md#catalog-metadata).",
            "",
        )
    )
    return "\n".join(lines)


def _plural(count: int, noun: str = "example") -> str:
    return f"{count} {noun if count == 1 else noun + 's'}"


def _render_category_tile(
    browse_id: str,
    title: str,
    description: str,
    count: int,
    *,
    is_collection: bool,
) -> str:
    tile_classes = "category-tile"
    if is_collection:
        tile_classes += " category-tile-collection"
    collection_label = "\n      <small>Collection</small>" if is_collection else ""
    info_id = f"{browse_id}-description"
    return f'''<div class="{tile_classes}" data-empty="{str(count == 0).lower()}">
  <a class="category-tile-link" href="?category={browse_id}#catalog">
    <span class="category-name">{html.escape(title)}{collection_label}</span>
    <span class="category-count">{_plural(count)} <span aria-hidden="true">→</span></span>
  </a>
  <div class="category-info" data-category-info>
    <button type="button" aria-label="About {html.escape(title, quote=True)}" aria-controls="{info_id}" aria-expanded="false"><span aria-hidden="true">i</span></button>
    <p id="{info_id}" role="tooltip">{html.escape(description)}</p>
  </div>
</div>'''


def render_category_nav(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    grouped = group_entries(entries, categories)
    tiles = []
    for category in categories:
        count = len(grouped[category.id])
        tiles.append(
            _render_category_tile(
                category.id,
                category.title,
                category.description,
                count,
                is_collection=False,
            )
        )
    for collection in collections:
        tiles.append(
            _render_category_tile(
                collection.browse_id,
                collection.title,
                collection.description,
                len(entries_for_collection(entries, collection)),
                is_collection=True,
            )
        )
    return "\n".join(tiles)


def render_industry_nav(entries: list[CatalogEntry]) -> str:
    counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        counts[entry.industry] += 1
    return "\n".join(
        "\n".join(
            (
                f'<a class="industry-tile" data-empty="{str(counts[industry] == 0).lower()}" '
                f'href="?view=industry&amp;industry={slugify(industry)}#catalog">',
                f'  <span>{html.escape(INDUSTRY_EMOJIS[industry])} '
                f'{html.escape(industry).replace("/", "/<wbr>")}</span>',
                f'  <span class="industry-tile-count" aria-label="{_plural(counts[industry])}">'
                f'{counts[industry]}</span>',
                "</a>",
            )
        )
        for industry in INDUSTRIES
    )


def category_filter_options(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    grouped = group_entries(entries, categories)
    recipe_categories = tuple(
        category for category in categories if category.kind == "recipe"
    )
    other_categories = tuple(
        category for category in categories if category.kind != "recipe"
    )
    recipe_options = "\n".join(
        f'<option value="{category.id}">{html.escape(category.title)} '
        f'({len(grouped[category.id])})</option>'
        for category in recipe_categories
    )
    other_options = "\n".join(
        f'<option value="{category.id}">{html.escape(category.title)} '
        f'({len(grouped[category.id])})</option>'
        for category in other_categories
    )
    collection_options = "\n".join(
        f'<option value="{collection.browse_id}">{html.escape(collection.title)} '
        f'({len(entries_for_collection(entries, collection))})</option>'
        for collection in collections
    )
    return "\n".join(
        (
            f'<option value="all">All examples ({len(entries)})</option>',
            '<optgroup label="Recipes by source">',
            indent(recipe_options, 2),
            "</optgroup>",
            '<optgroup label="Collections">',
            indent(collection_options, 2),
            "</optgroup>",
            '<optgroup label="Other example formats">',
            indent(other_options, 2),
            "</optgroup>",
        )
    )


def industry_filter_options(entries: list[CatalogEntry]) -> str:
    counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        counts[entry.industry] += 1
    options = [f'<option value="all">All industries ({len(entries)})</option>']
    options.extend(
        f'<option value="{slugify(industry)}">{html.escape(INDUSTRY_EMOJIS[industry])} '
        f'{html.escape(industry)} ({counts[industry]})</option>'
        for industry in INDUSTRIES
    )
    return "\n".join(options)


def maintenance_filter_options(entries: list[CatalogEntry]) -> str:
    """Render the computed maintenance facet and default maintained subset."""

    counts = {status: 0 for status in MAINTENANCE_STATUSES}
    for entry in entries:
        if entry.maintenance is None:
            raise CatalogError(f"Missing maintenance status for {entry.readme_path}.")
        counts[entry.maintenance.id] += 1
    maintained_count = sum(
        count for status_id, count in counts.items() if status_id != "deprecated"
    )
    return "\n".join(
        (
            f'<option value="maintained">Maintained examples ({maintained_count})</option>',
            f'<option value="all">All statuses ({len(entries)})</option>',
            f'<option value="current">Current ({counts["current"]})</option>',
            f'<option value="review-soon">Review soon '
            f'({counts["review-soon"]})</option>',
            f'<option value="review-due">Review due ({counts["review-due"]})</option>',
            f'<option value="review-overdue">Review overdue '
            f'({counts["review-overdue"]})</option>',
            f'<option value="deprecated">Deprecated ({counts["deprecated"]})</option>',
        )
    )


def render_card(entry: CatalogEntry) -> str:
    if entry.maintenance is None:
        raise CatalogError(f"Missing maintenance status for {entry.readme_path}.")
    collections = " ".join(entry.collection_ids)
    collection_tags = "".join(
        f'<li class="tag tag-collection">{html.escape(collection.metadata_value)}</li>'
        for collection in entry.collections
    )
    return f'''<article
  class="example-card"
  id="{entry.id}"
  aria-labelledby="{entry.id}-title"
  data-catalog-entry
  data-name="{html.escape(entry.title, quote=True)}"
  data-readme="{html.escape(entry.readme_path, quote=True)}"
  data-category="{entry.category.id}"
  data-industry="{entry.industry_id}"
  data-maintenance="{entry.maintenance.id}"
  data-collections="{html.escape(collections, quote=True)}"
  data-search="{html.escape(entry.search_text, quote=True)}"
  tabindex="-1"
>
  <p class="provenance">{html.escape(entry.display_label)}</p>
  <h3 id="{entry.id}-title"><a class="example-title-link" href="{entry.detail_url}">{html.escape(entry.title)}</a></h3>
  <p class="outcome">{html.escape(entry.description)}</p>
  <ul class="card-tags" aria-label="Discovery fields">
    <li class="tag">{html.escape(entry.industry_label)}</li>{collection_tags}
  </ul>
  <dl class="requirements">
    <div><dt>Requirements &amp; limits</dt><dd>{html.escape(entry.requirements)}</dd></div>
  </dl>
  <div class="card-footer">
    <a class="card-action" href="{entry.detail_url}">View example<span class="sr-only">: {html.escape(entry.title)}</span>&nbsp;<span aria-hidden="true">→</span></a>
  </div>
</article>'''


def render_catalog_groups(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
) -> str:
    grouped = group_entries(entries, categories)
    sections = []
    for category in categories:
        cards = "\n".join(render_card(entry) for entry in grouped[category.id])
        sections.append(
            f'''<section
  class="catalog-group"
  id="{category.id}"
  tabindex="-1"
  data-catalog-category="{category.id}"
  aria-labelledby="{category.id}-title"
>
  <div class="shell group-layout">
    <header class="group-heading">
      <h2 id="{category.id}-title">{html.escape(category.title)}</h2>
      <p>{html.escape(category.description)}</p>
    </header>
    <div class="card-grid">
{indent(cards, 6)}
    </div>
  </div>
</section>'''
        )
    return "\n".join(sections)


def indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in value.splitlines())


def render_site(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
    template: str,
) -> str:
    represented_industries = len({entry.industry for entry in entries})
    replacements = {
        "{{EXAMPLE_COUNT}}": str(len(entries)),
        "{{INDUSTRY_COUNT}}": str(len(INDUSTRIES)),
        "{{REPRESENTED_INDUSTRY_COUNT}}": str(represented_industries),
        "{{BROWSE_GROUP_COUNT}}": str(len(categories) + len(collections)),
        "{{CATEGORY_NAV}}": indent(
            render_category_nav(entries, categories, collections), 14
        ),
        "{{INDUSTRY_NAV}}": indent(render_industry_nav(entries), 14),
        "{{CATEGORY_OPTIONS}}": indent(
            category_filter_options(entries, categories, collections), 18
        ),
        "{{INDUSTRY_OPTIONS}}": indent(industry_filter_options(entries), 18),
        "{{MAINTENANCE_OPTIONS}}": indent(
            maintenance_filter_options(entries), 18
        ),
        "{{CATALOG_GROUPS}}": indent(
            render_catalog_groups(entries, categories), 8
        ),
    }
    rendered = template
    for marker, value in replacements.items():
        count = rendered.count(marker)
        expected_count = 2 if marker == "{{EXAMPLE_COUNT}}" else 1
        if count != expected_count:
            raise CatalogError(
                f"Expected {expected_count} {marker} marker(s) in "
                "site/index.template.html."
            )
        rendered = rendered.replace(marker, value)
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
    if leftover:
        raise CatalogError("Unknown template markers: " + ", ".join(sorted(leftover)))
    return rendered


def public_catalog(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
    policy: MaintenancePolicy,
    snapshot: MaintenanceSnapshot,
    as_of: dt.date,
) -> dict[str, Any]:
    grouped = group_entries(entries, categories)
    for entry in entries:
        if entry.maintenance is None or entry.last_content_change_on is None:
            raise CatalogError(f"Missing maintenance status for {entry.readme_path}.")
    industry_counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        industry_counts[entry.industry] += 1

    return {
        "schema_version": 6,
        "source": "https://github.com/NVIDIA/nemoclaw-community/tree/main/examples",
        "maintenance": {
            "as_of": as_of.isoformat(),
            "dependencies_checked_at": snapshot.checked_at,
            "thresholds": {
                "dependency_warning_days": policy.dependency_warning_days,
                "dependency_overdue_days": policy.dependency_overdue_days,
                "review_overdue_days": policy.review_overdue_days,
                "deprecation_days": policy.deprecation_days,
            },
            "states": [
                {
                    "id": status_id,
                    "label": label,
                    "count": sum(
                        entry.maintenance is not None
                        and entry.maintenance.id == status_id
                        for entry in entries
                    ),
                }
                for status_id, label in MAINTENANCE_STATUSES.items()
            ],
            "dependencies": [
                {
                    "id": dependency.id,
                    "label": dependency.label,
                    "repository": dependency.repository,
                    "source": dependency.source,
                    "channel": dependency.channel,
                    "latest": {
                        "tag": snapshot.releases[dependency.id].tag,
                        "component_version": snapshot.releases[
                            dependency.id
                        ].component_version,
                        "published_on": snapshot.releases[
                            dependency.id
                        ].published_on.isoformat(),
                        "url": snapshot.releases[dependency.id].url,
                    },
                }
                for dependency in policy.dependencies
            ],
        },
        "categories": [
            {
                "id": category.id,
                "label": category.title,
                "description": category.description,
                "kind": category.kind,
                "provenance": category.provenance,
                "count": len(grouped[category.id]),
                "source_path": category.readme_path,
            }
            for category in categories
        ],
        "industries": [
            {
                "id": slugify(industry),
                "label": industry,
                "emoji": INDUSTRY_EMOJIS[industry],
                "count": industry_counts[industry],
            }
            for industry in INDUSTRIES
        ],
        "collections": [
            {
                "id": collection.id,
                "browse_id": collection.browse_id,
                "label": collection.title,
                "description": collection.description,
                "count": len(entries_for_collection(entries, collection)),
                "source_path": collection.readme_path,
            }
            for collection in collections
        ],
        "examples": [
            {
                "id": entry.id,
                "title": entry.title,
                "description": entry.description,
                "industry": {
                    "id": entry.industry_id,
                    "label": entry.industry,
                    "emoji": entry.industry_emoji,
                },
                "kind": entry.category.kind,
                "provenance": entry.category.provenance,
                "category": {
                    "id": entry.category.id,
                    "label": entry.category.title,
                },
                "contributor": entry.contributor,
                "collections": list(entry.collection_ids),
                "requirements": entry.requirements,
                "stack": (
                    {
                        "status": entry.stack_status,
                        "harness": {
                            "id": entry.stack.harness,
                            "label": HARNESS_PRESENTATION[entry.stack.harness]["label"],
                            "version": entry.stack.harness_version,
                            "url": HARNESS_PRESENTATION[entry.stack.harness]["url"],
                        },
                        "openshell": {
                            "version": entry.stack.openshell_version,
                            "url": "https://github.com/NVIDIA/OpenShell",
                        },
                    }
                    if entry.stack is not None
                    else {"status": entry.stack_status}
                ),
                "maintenance": {
                    "status": entry.maintenance.id,
                    "label": entry.maintenance.label,
                    "lifecycle": entry.lifecycle,
                    "last_content_change": entry.last_content_change_on.isoformat(),
                    "reviewed": (
                        entry.reviewed_on.isoformat() if entry.reviewed_on else None
                    ),
                    "effective_date": entry.maintenance.effective_on.isoformat(),
                    "activity_source": entry.maintenance.activity_source,
                    "dependencies_checked_on": entry.maintenance.checked_on.isoformat(),
                    "explanation": entry.maintenance.explanation,
                },
                "upstream_url": entry.upstream_url,
                "source_path": entry.readme_path,
                "guide_url": entry.guide_url,
                "detail_url": entry.detail_url,
            }
            for entry in entries
        ],
    }


def render_llms(entries: list[CatalogEntry]) -> str:
    """Render a concise website-navigation index for language-model clients."""

    lines = [
        "# NemoClaw Community",
        "",
        "> A catalog of constrained, inspectable agent recipes, field demos, and developer tools built with NemoClaw.",
        "",
        "Use the industry, category, and maintenance fields below to select an example. Requirements are short summaries; read the linked source guide before running an example.",
        "",
        "## Catalog data",
        "",
        f"- [Browse the catalog]({PAGES_BASE_URL})",
        f"- [Machine-readable catalog]({PAGES_BASE_URL}catalog.json)",
        "",
        "## Examples",
        "",
    ]
    for entry in entries:
        if entry.maintenance is None:
            raise CatalogError(f"Missing maintenance status for {entry.readme_path}.")
        lines.extend(
            (
                f"- [{entry.title}]({entry.absolute_detail_url})",
                f"  - Description: {entry.description}",
                f"  - Category: {entry.category.title}",
                f"  - Industry: {entry.industry_label}",
                f"  - Requirements: {entry.requirements}",
                f"  - Maintenance: {entry.maintenance.label} ({entry.lifecycle}); "
                f"{entry.maintenance.explanation}",
                f"  - Maintenance activity: {entry.maintenance.effective_on.isoformat()} "
                f"({entry.maintenance.activity_source})",
                f"  - Source: [README]({entry.guide_url})",
            )
        )
        if entry.stack is not None:
            lines.append(
                f"  - Harness: {entry.stack.harness_label} "
                f"{entry.stack.harness_version}"
            )
            lines.append(
                "  - OpenShell: "
                + (entry.stack.openshell_version or "N/A")
            )
        else:
            value = "N/A" if entry.stack_status == "not-applicable" else "Not declared"
            lines.extend((f"  - Harness: {value}", f"  - OpenShell: {value}"))
        if entry.collections:
            lines.append(
                "  - Collections: "
                + ", ".join(collection.title for collection in entry.collections)
            )
        if entry.upstream_url:
            lines.append(f"  - Upstream: [Project](<{entry.upstream_url}>)")
    lines.append("")
    return "\n".join(lines)


def taxonomy_contract() -> dict[str, Any]:
    """Return stable browser identifiers for cross-language contract tests."""

    return {
        "categories": [
            "all",
            *(category.id for category in CATEGORY_DEFINITIONS),
            *(collection.browse_id for collection in COLLECTION_DEFINITIONS),
        ],
        "collection_categories": {
            collection.browse_id: collection.id
            for collection in COLLECTION_DEFINITIONS
        },
        "industries": ["all", *(slugify(industry) for industry in INDUSTRIES)],
        "maintenance": [
            "maintained",
            "all",
            *MAINTENANCE_STATUSES,
        ],
    }


def github_heading_slug(value: str, separator: str) -> str:
    """Approximate GitHub's stable heading IDs for README fragment links."""

    normalized = html.unescape(value).strip().casefold()
    normalized = re.sub(r"[^\w\-\ufe0f ]", "", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", separator, normalized)


def extract_mermaid_sources(content: str, readme_path: str) -> tuple[str, ...]:
    """Return Mermaid fences after enforcing the catalog's safe diagram subset."""

    opening_count = len(MERMAID_FENCE_OPEN_PATTERN.findall(content))
    matches = list(MERMAID_FENCE_PATTERN.finditer(content))
    if opening_count != len(matches):
        raise CatalogError(
            f"Mermaid fence is not closed correctly in {readme_path}."
        )
    if len(matches) > MAX_MERMAID_DIAGRAMS_PER_README:
        raise CatalogError(
            f"{readme_path} has more than {MAX_MERMAID_DIAGRAMS_PER_README} "
            "Mermaid diagrams."
        )

    sources: list[str] = []
    for index, match in enumerate(matches, start=1):
        source = match.group("source").strip()
        label = f"Mermaid diagram {index} in {readme_path}"
        if not source:
            raise CatalogError(f"{label} is empty.")
        if len(source) > MAX_MERMAID_SOURCE_SIZE:
            raise CatalogError(
                f"{label} exceeds the {MAX_MERMAID_SOURCE_SIZE}-character limit."
            )

        first_line = source.splitlines()[0].strip()
        diagram_type = first_line.split(maxsplit=1)[0]
        if diagram_type not in MERMAID_DIAGRAM_TYPES:
            raise CatalogError(
                f"{label} uses unsupported type {diagram_type!r}. Supported types: "
                + ", ".join(sorted(MERMAID_DIAGRAM_TYPES))
                + "."
            )
        if diagram_type in {"flowchart", "graph"} and re.fullmatch(
            r"(?:flowchart|graph)\s+(?:BT|LR|RL|TB|TD)", first_line
        ) is None:
            raise CatalogError(
                f"{label} must declare one supported flow direction on its first line."
            )
        if diagram_type in {"sequenceDiagram", "stateDiagram-v2"} and (
            first_line != diagram_type
        ):
            raise CatalogError(
                f"{label} has unexpected content after its diagram type."
            )
        for pattern, description in MERMAID_FORBIDDEN_SOURCE_PATTERNS:
            if pattern.search(source):
                raise CatalogError(f"{label} contains forbidden {description}.")
        sources.append(source)
    return tuple(sources)


class ReadmeHTMLSanitizer(HTMLParser):
    """Allow the Markdown subset used by example READMEs and rewrite local URLs."""

    ALLOWED_TAGS = {
        "a",
        "abbr",
        "blockquote",
        "br",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
    VOID_TAGS = {"br", "hr", "img"}

    def __init__(
        self,
        root: Path,
        entry: CatalogEntry,
        catalog_by_readme: dict[str, CatalogEntry],
        copied_assets: set[str],
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.root = root
        self.entry = entry
        self.catalog_by_readme = catalog_by_readme
        self.copied_assets = copied_assets
        self.output: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self._open_tags: list[str] = []
        self._source_dir = PurePosixPath(entry.readme_path).parent.as_posix()
        self._detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()

    def _repo_target(self, raw_path: str) -> str | None:
        decoded_path = raw_path.replace("\\", "/")
        if decoded_path.startswith("/"):
            target = posixpath.normpath(decoded_path.lstrip("/"))
        else:
            target = posixpath.normpath(posixpath.join(self._source_dir, decoded_path))
        if target == ".." or target.startswith("../"):
            self.errors.append(f"README URL escapes the repository: {raw_path}")
            return None
        return target

    def _rewrite_href(self, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme:
            if parts.scheme not in {"https", "mailto"}:
                self.errors.append(f"Unsupported README link scheme: {value}")
                return "#"
            return value
        if parts.netloc:
            self.errors.append(f"Protocol-relative README link is not allowed: {value}")
            return "#"
        if not parts.path:
            if parts.fragment:
                self.fragments.add(parts.fragment)
            return value
        target = self._repo_target(parts.path)
        if target is None:
            return "#"
        target_path = self.root / target
        if not target_path.exists():
            self.errors.append(
                f"README link target does not exist in the repository: {value}"
            )
            return "#"
        if target == self.entry.readme_path:
            rewritten_path = ""
            if parts.fragment:
                self.fragments.add(unquote(parts.fragment))
        elif target in self.catalog_by_readme:
            target_detail_dir = PurePosixPath(
                self.catalog_by_readme[target].detail_path
            ).parent.as_posix()
            rewritten_path = posixpath.relpath(target_detail_dir, self._detail_dir) + "/"
        else:
            route = "tree" if target_path.is_dir() else "blob"
            rewritten_path = (
                f"https://github.com/NVIDIA/nemoclaw-community/{route}/main/"
                f"{quote(target, safe='/')}"
            )
        return urlunsplit(("", "", rewritten_path, parts.query, parts.fragment))

    def _rewrite_src(self, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme:
            self.errors.append(
                f"Remote README images must render as outbound links: {value}"
            )
            return ""
        if parts.netloc:
            self.errors.append(f"Protocol-relative README image is not allowed: {value}")
            return ""
        target = self._repo_target(parts.path)
        if target is None:
            return ""
        target_path = self.root / target
        if not is_regular_repo_file(self.root, target_path):
            self.errors.append(f"README image target is not a regular file: {value}")
            return ""
        if target_path.suffix.casefold() not in {
            ".gif",
            ".jpeg",
            ".jpg",
            ".png",
            ".webp",
        }:
            self.errors.append(f"Unsupported README image type: {value}")
            return ""
        if target_path.stat().st_size > 5 * 1024 * 1024:
            self.errors.append(f"README image exceeds the 5 MiB limit: {value}")
            return ""
        self.copied_assets.add(target)
        relative = posixpath.relpath(target, self._detail_dir)
        return urlunsplit(("", "", relative, parts.query, parts.fragment))

    def _safe_attributes(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> list[tuple[str, str]]:
        values = {name: value or "" for name, value in attrs}
        safe: list[tuple[str, str]] = []
        if tag == "a":
            href = values.get("href")
            if href is None:
                self.errors.append("README link is missing href.")
            else:
                safe.append(("href", self._rewrite_href(href)))
            if values.get("title"):
                safe.append(("title", values["title"]))
        elif tag == "img":
            src = values.get("src")
            alt = values.get("alt")
            if not src:
                self.errors.append("README image is missing src.")
            else:
                safe.append(("src", self._rewrite_src(src)))
            if alt is None or not alt.strip():
                self.errors.append("README image is missing meaningful alt text.")
            else:
                safe.append(("alt", alt))
            for name in ("title", "width", "height"):
                if values.get(name):
                    if name in {"width", "height"} and not values[name].isdigit():
                        self.errors.append(f"README image {name} must be numeric.")
                    else:
                        safe.append((name, values[name]))
            safe.extend((("loading", "lazy"), ("decoding", "async")))
        elif tag in {"h2", "h3", "h4", "h5", "h6"}:
            heading_id = values.get("id")
            if not heading_id:
                self.errors.append(f"README {tag} is missing a generated id.")
            elif heading_id in self.ids:
                self.errors.append(f"Duplicate README heading id: {heading_id}")
            else:
                self.ids.add(heading_id)
                safe.append(("id", heading_id))
        elif tag == "code" and values.get("class"):
            class_name = values["class"]
            if re.fullmatch(r"language-[A-Za-z0-9_+.-]+", class_name):
                safe.append(("class", class_name))
            else:
                self.errors.append(f"Unexpected README code class: {class_name}")
        elif tag in {"th", "td"} and values.get("align"):
            if values["align"] not in {"left", "center", "right"}:
                self.errors.append(f"Unexpected README table alignment: {values['align']}")
            else:
                safe.append(("align", values["align"]))
        elif tag == "ol" and values.get("start"):
            if values["start"].isdigit():
                safe.append(("start", values["start"]))
            else:
                self.errors.append("README ordered-list start must be numeric.")
        elif tag == "abbr" and values.get("title"):
            safe.append(("title", values["title"]))
        elif tag == "div":
            if values.get("class") == "toc":
                safe.append(("class", "toc"))
            else:
                self.errors.append(
                    "Only the generated README table-of-contents div is allowed."
                )

        allowed_names = {name for name, _ in safe}
        ignored_generated = {"class"} if tag == "div" else set()
        unexpected = set(values) - allowed_names - ignored_generated
        if unexpected:
            self.errors.append(
                f"Unsupported attributes on README {tag}: "
                + ", ".join(sorted(unexpected))
            )
        return safe

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        self_closing: bool,
    ) -> None:
        if tag not in self.ALLOWED_TAGS:
            self.errors.append(f"Unsupported README HTML element: {tag}")
            return
        if tag == "img":
            values = {name: value or "" for name, value in attrs}
            source = values.get("src", "")
            source_parts = urlsplit(source)
            if source_parts.scheme or source_parts.netloc:
                alt = values.get("alt", "").strip()
                if source_parts.scheme != "https" or source_parts.netloc == "":
                    self.errors.append(f"Remote README image must use HTTPS: {source}")
                    return
                if not alt:
                    self.errors.append("Remote README image is missing meaningful alt text.")
                    return
                self.output.append(
                    '<a class="readme-image-link" href="'
                    f'{html.escape(source, quote=True)}">View image: '
                    f'{html.escape(alt)} <span aria-hidden="true">↗</span></a>'
                )
                return
        if tag == "table":
            self.output.append('<div class="table-wrapper">')
        safe_attrs = self._safe_attributes(tag, attrs)
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")
        if not self_closing and tag not in self.VOID_TAGS:
            self._open_tags.append(tag)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, False)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.ALLOWED_TAGS or tag in self.VOID_TAGS:
            return
        if not self._open_tags or self._open_tags[-1] != tag:
            self.errors.append(f"Unbalanced README HTML closing tag: {tag}")
            return
        self._open_tags.pop()
        self.output.append(f"</{tag}>")
        if tag == "table":
            self.output.append("</div>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data))

    def handle_comment(self, data: str) -> None:
        return

    def result(self) -> str:
        if self._open_tags:
            self.errors.append(
                "Unclosed README HTML elements: " + ", ".join(self._open_tags)
            )
        if self.errors:
            raise CatalogError("\n".join(self.errors))
        return "".join(self.output)


def render_readme_html(
    root: Path,
    entry: CatalogEntry,
    catalog_by_readme: dict[str, CatalogEntry],
    copied_assets: set[str],
) -> tuple[str, str, str, bool]:
    """Compile one source README to sanitized themed-page HTML."""

    if markdown is None:
        raise CatalogError(
            "Catalog detail pages require the pinned Markdown package. Run "
            "`python3 -m pip install --require-hashes -r "
            "scripts/catalog-requirements.txt`."
        )
    source = (root / entry.readme_path).read_text(encoding="utf-8")
    mermaid_sources = extract_mermaid_sources(source, entry.readme_path)
    from markdown.extensions.tables import TableExtension

    renderer = markdown.Markdown(
        extensions=[
            "fenced_code",
            TableExtension(use_align_attribute=True),
            "sane_lists",
            "toc",
        ],
        extension_configs={
            "toc": {
                "slugify": github_heading_slug,
                "toc_depth": "2-3",
            }
        },
        output_format="html5",
    )
    rendered_body = renderer.convert(entry.readme_body)
    body_sanitizer = ReadmeHTMLSanitizer(
        root, entry, catalog_by_readme, copied_assets
    )
    body_sanitizer.feed(rendered_body)
    safe_body = body_sanitizer.result()

    if renderer.toc:
        toc_sanitizer = ReadmeHTMLSanitizer(
            root, entry, catalog_by_readme, copied_assets
        )
        toc_sanitizer.feed(renderer.toc)
        safe_toc = toc_sanitizer.result()
        unresolved_toc = toc_sanitizer.fragments - body_sanitizer.ids
        if unresolved_toc:
            raise CatalogError(
                f"Generated README table of contents has unresolved fragments for "
                f"{entry.readme_path}: "
                + ", ".join(sorted(unresolved_toc))
            )
    else:
        safe_toc = '<p class="toc-empty">This short guide has no subsections.</p>'
    unresolved_fragments = body_sanitizer.fragments - body_sanitizer.ids
    if unresolved_fragments:
        raise CatalogError(
            f"README has unresolved local fragments for {entry.readme_path}: "
            + ", ".join(sorted(unresolved_fragments))
        )
    rendered_mermaid_count = safe_body.count('class="language-mermaid"')
    if rendered_mermaid_count != len(mermaid_sources):
        raise CatalogError(
            f"Mermaid source/render count mismatch for {entry.readme_path}."
        )
    return entry.title, safe_body, safe_toc, bool(mermaid_sources)


def _detail_relative(entry: CatalogEntry, target: str) -> str:
    detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()
    return posixpath.relpath(target, detail_dir)


def render_detail_pages(
    root: Path,
    entries: list[CatalogEntry],
    template: str,
) -> tuple[dict[str, str], set[str]]:
    """Render one static, themed README page per catalog entry."""

    catalog_by_readme = {entry.readme_path: entry for entry in entries}
    copied_assets: set[str] = set()
    pages: dict[str, str] = {}
    for entry in entries:
        if entry.maintenance is None:
            raise CatalogError(f"Missing maintenance status for {entry.readme_path}.")
        readme_title, readme_html, toc_html, has_mermaid = render_readme_html(
            root, entry, catalog_by_readme, copied_assets
        )
        collection_tags = "".join(
            f'\n              <li class="tag tag-collection">'
            f'{html.escape(collection.metadata_value)}</li>'
            for collection in entry.collections
        )
        if entry.contributor:
            attribution_fact = (
                f"<div><dt>Contributor</dt><dd>{html.escape(entry.contributor)}</dd></div>"
            )
        else:
            attribution_fact = ""
        upstream_fact = ""
        if entry.upstream_url:
            upstream_fact = (
                "<div><dt>Upstream project</dt><dd>"
                f'<a href="{html.escape(entry.upstream_url, quote=True)}">'
                "View upstream project <span aria-hidden=\"true\">↗</span>"
                "</a></dd></div>"
            )
        diagram_scripts = ""
        if has_mermaid:
            mermaid_url = _detail_relative(
                entry, "assets/vendor/mermaid.tiny.js"
            )
            diagrams_url = _detail_relative(entry, "diagrams.mjs")
            diagram_scripts = (
                f'    <script src="{mermaid_url}" integrity="{MERMAID_SRI}"></script>\n'
                f'    <script type="module" src="{diagrams_url}"></script>'
            )
        stack_facts = (
            '<div class="stack-fact"><dt>Harness</dt><dd>Not declared</dd></div>'
            '<div class="stack-fact"><dt>OpenShell</dt><dd>Not declared</dd></div>'
        )
        if entry.stack_status == "not-applicable":
            stack_facts = (
                '<div class="stack-fact"><dt>Harness</dt><dd>N/A</dd></div>'
                '<div class="stack-fact"><dt>OpenShell</dt><dd>N/A</dd></div>'
            )
        if entry.stack is not None:
            presentation = HARNESS_PRESENTATION[entry.stack.harness]
            openshell_version = entry.stack.openshell_version
            openshell_fact = (
                '<a href="https://github.com/NVIDIA/OpenShell">'
                f'{html.escape(openshell_version)}</a>'
                if openshell_version is not None
                else "N/A"
            )
            stack_facts = (
                '<div class="stack-fact"><dt>Harness</dt><dd>'
                f'<a class="harness-identity" href="{presentation["url"]}">'
                f'<span class="harness-mark harness-mark-{entry.stack.harness}" '
                f'aria-hidden="true">{presentation["mark"]}</span>'
                f'<span>{html.escape(presentation["label"])} '
                f'<span class="stack-version">{html.escape(entry.stack.harness_version)}'
                '</span></span></a></dd></div>'
                '<div class="stack-fact"><dt>OpenShell</dt><dd>'
                f'{openshell_fact}</dd></div>'
            )
        maintenance_fact = (
            f'<div class="maintenance-fact" data-maintenance="{entry.maintenance.id}">'
            '<dt id="maintenance-status-title">Maintenance</dt><dd>'
            f'<span class="maintenance-badge">'
            f'{html.escape(entry.maintenance.label)}</span>'
            '<details class="maintenance-info">'
            '<summary aria-label="Maintenance status details" '
            'aria-controls="maintenance-details">'
            '<span aria-hidden="true">i</span></summary></details>'
            '<span class="maintenance-popover" id="maintenance-details" '
            'role="region" aria-label="Maintenance activity">'
            '<span class="maintenance-popover-title">Maintenance activity</span>'
            f'<span class="maintenance-popover-copy">'
            f'{html.escape(entry.maintenance.explanation)}</span>'
            '<span class="maintenance-popover-meta">'
            '<strong>Last maintenance activity</strong>'
            f'<span>{entry.maintenance.effective_on.isoformat()} · '
            f'{html.escape(entry.maintenance.activity_source)}</span></span>'
            '<span class="maintenance-popover-meta">'
            '<strong>Status calculated</strong>'
            f'<span>{entry.maintenance.as_of.isoformat()}</span></span>'
            '<span class="maintenance-popover-meta">'
            '<strong>Dependencies checked through</strong>'
            f'<span>{entry.maintenance.checked_on.isoformat()}</span></span>'
            "</span></dd></div>"
        )
        replacements = {
            "{{META_DESCRIPTION}}": html.escape(entry.description, quote=True),
            "{{PAGE_TITLE}}": html.escape(readme_title),
            "{{FAVICON_URL}}": _detail_relative(
                entry, "assets/nvidia-favicon.png"
            ),
            "{{STYLES_URL}}": _detail_relative(entry, "styles.css"),
            "{{LOGO_URL}}": _detail_relative(entry, "assets/nvidia-logo.png"),
            "{{CATALOG_URL}}": _detail_relative(entry, "index.html"),
            "{{SOURCE_URL}}": html.escape(entry.guide_url, quote=True),
            "{{DISPLAY_LABEL}}": html.escape(entry.display_label),
            "{{DESCRIPTION}}": html.escape(entry.description),
            "{{INDUSTRY}}": html.escape(entry.industry_label),
            "{{COLLECTION_TAGS}}": collection_tags,
            "{{CATEGORY}}": html.escape(entry.category.singular),
            "{{ATTRIBUTION_FACT}}": attribution_fact,
            "{{UPSTREAM_FACT}}": upstream_fact,
            "{{STACK_FACTS}}": stack_facts,
            "{{REQUIREMENTS}}": html.escape(entry.requirements),
            "{{MAINTENANCE_FACT}}": maintenance_fact,
            "{{TABLE_OF_CONTENTS}}": toc_html,
            "{{README_HTML}}": indent(readme_html, 12),
            "{{DIAGRAM_SCRIPTS}}": diagram_scripts,
        }
        rendered = template
        for marker, value in replacements.items():
            expected_counts = {
                "{{CATALOG_URL}}": 3,
                "{{INDUSTRY}}": 2,
                "{{PAGE_TITLE}}": 2,
                "{{SOURCE_URL}}": 2,
                "{{TABLE_OF_CONTENTS}}": 2,
            }
            expected_count = expected_counts.get(marker, 1)
            if rendered.count(marker) != expected_count:
                raise CatalogError(
                    f"Expected {expected_count} {marker} marker(s) in "
                    "site/detail.template.html."
                )
            rendered = rendered.replace(marker, value)
        leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
        if leftover:
            raise CatalogError(
                "Unknown detail template markers: " + ", ".join(sorted(leftover))
            )
        pages[entry.detail_path] = rendered
    return pages, copied_assets


class GeneratedHTMLValidator(HTMLParser):
    """Small dependency-free safety and accessibility check for generated HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self.cards: list[dict[str, str]] = []
        self.category_groups: list[dict[str, str]] = []
        self.category_info_controls: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.links: set[str] = set()
        self.resources: list[str] = []
        self.labels_for: set[str] = set()
        self.tag_counts: dict[str, int] = {}
        self.content_security_policies: list[str] = []
        self.html_language = ""
        self.has_viewport = False
        self.h1_count = 0
        self._inside_script = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {name: value or "" for name, value in attrs}
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag == "html":
            self.html_language = values.get("lang", "")
        if tag == "meta" and values.get("name") == "viewport":
            self.has_viewport = bool(values.get("content"))
        if tag == "meta" and values.get("http-equiv", "").casefold() == (
            "content-security-policy"
        ):
            self.content_security_policies.append(values.get("content", ""))
        if tag == "label" and values.get("for"):
            self.labels_for.add(values["for"])
        if tag == "a" and values.get("href"):
            self.anchors.append(values)
            self.links.add(values["href"])
        if tag in {"iframe", "object", "embed"}:
            self.errors.append(f"Forbidden embedded resource element: {tag}")
        if tag == "img" and not values.get("alt"):
            self.errors.append("Every catalog image must have non-empty alt text.")
        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.errors.append(f"Duplicate HTML id: {element_id}")
            self.ids.add(element_id)
        if tag == "h1":
            self.h1_count += 1
        if tag == "article" and "data-catalog-entry" in values:
            self.cards.append(values)
        if tag == "section" and "data-catalog-category" in values:
            self.category_groups.append(values)
        if tag == "button" and values.get("aria-controls", "").endswith(
            "-description"
        ):
            self.category_info_controls.append(values)
        if tag == "script":
            self.scripts.append(values)
            self._inside_script = True
        for name, value in values.items():
            if name.startswith("on"):
                self.errors.append(f"Inline event handler is not allowed: {name}")
            if name == "style":
                self.errors.append("Inline style attributes are not allowed.")
            if name in {"href", "src"}:
                if value.startswith("/"):
                    self.errors.append(f"Root-relative URL breaks project Pages: {value}")
                if value.startswith("#"):
                    self.fragments.add(unquote(value[1:]))
        if tag in {"img", "link", "script"}:
            resource = values.get("src") or values.get("href") or ""
            if resource:
                self.resources.append(resource)
            if resource.startswith(("http://", "https://", "//")):
                self.errors.append(f"Remote page resource is not allowed: {resource}")
        if tag == "form" and values.get("action"):
            self.errors.append("The catalog filter form must not submit externally.")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_script and data.strip():
            self.errors.append("Inline script content is not allowed.")


def validate_generated_site(
    root: Path,
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
    site_html: str,
) -> None:
    parser = GeneratedHTMLValidator()
    parser.feed(site_html)
    errors = list(parser.errors)
    required_ids = {
        "browse-category-panel",
        "browse-industry-panel",
        "catalog",
        "catalog-controls",
        "catalog-search",
        "catalog-view-category",
        "catalog-view-controls",
        "catalog-view-industry",
        "catalog-category",
        "catalog-industry",
        "catalog-maintenance",
        "catalog-reset",
        "catalog-status",
        "catalog-empty",
        "catalog-results",
    }
    missing_ids = required_ids - parser.ids
    if missing_ids:
        errors.append("Missing required catalog IDs: " + ", ".join(sorted(missing_ids)))
    unresolved_fragments = parser.fragments - parser.ids
    if unresolved_fragments:
        errors.append(
            "Unresolved HTML fragments: " + ", ".join(sorted(unresolved_fragments))
        )
    if parser.h1_count != 1:
        errors.append(f"Expected exactly one h1; found {parser.h1_count}.")
    if parser.html_language != "en":
        errors.append("The generated page must declare html lang=\"en\".")
    if not parser.has_viewport:
        errors.append("The generated page must include a viewport meta tag.")
    if parser.tag_counts.get("header", 0) < 1:
        errors.append("The generated page must include a header landmark.")
    for landmark in ("main", "footer"):
        if parser.tag_counts.get(landmark) != 1:
            errors.append(f"Expected exactly one {landmark} landmark.")
    required_labels = {
        "catalog-search",
        "catalog-view-category",
        "catalog-view-industry",
        "catalog-category",
        "catalog-industry",
        "catalog-maintenance",
    }
    missing_labels = required_labels - parser.labels_for
    if missing_labels:
        errors.append(
            "Missing explicit control labels: " + ", ".join(sorted(missing_labels))
        )
    if parser.scripts != [{"type": "module", "src": "catalog.mjs"}]:
        errors.append("Expected exactly one local module script: catalog.mjs.")
    expected_resources = [
        "assets/nvidia-favicon.png",
        "styles.css",
        "assets/nvidia-logo.png",
        "catalog.mjs",
    ]
    if parser.resources != expected_resources:
        errors.append(
            "Generated local page resources changed unexpectedly: "
            + ", ".join(parser.resources)
        )

    expected_cards = [
        {
            "data-readme": entry.readme_path,
            "data-category": entry.category.id,
            "data-industry": entry.industry_id,
            "data-maintenance": (
                entry.maintenance.id if entry.maintenance else ""
            ),
            "data-collections": " ".join(entry.collection_ids),
        }
        for entry in entries
    ]
    actual_cards = [
        {key: card.get(key, "") for key in expected_cards[0]}
        for card in parser.cards
    ] if expected_cards else []
    if actual_cards != expected_cards:
        errors.append("Generated card metadata or order does not match the READMEs.")
    for entry, card in zip(entries, parser.cards):
        if card.get("id") != entry.id:
            errors.append(f"Generated card ID does not match {entry.title}.")
        if card.get("aria-labelledby") != f"{entry.id}-title":
            errors.append(f"Generated card label does not match {entry.title}.")
    for category in categories:
        category_attrs = next(
            (
                attrs
                for attrs in parser.category_groups
                if attrs.get("data-catalog-category") == category.id
            ),
            None,
        )
        if category_attrs is None or category_attrs.get("tabindex") != "-1":
            errors.append(f"Category fragment is not focusable: {category.id}")

    browse_groups: tuple[Category | Collection, ...] = (*categories, *collections)
    expected_info_controls = [
        {
            "aria-label": f"About {group.title}",
            "aria-controls": (
                f"{group.id}-description"
                if isinstance(group, Category)
                else f"{group.browse_id}-description"
            ),
            "aria-expanded": "false",
            "type": "button",
        }
        for group in browse_groups
    ]
    actual_info_controls = [
        {
            key: control.get(key, "") for key in expected_info_controls[0]
        }
        for control in parser.category_info_controls
    ] if expected_info_controls else []
    if actual_info_controls != expected_info_controls:
        errors.append("Browse-group information controls are incomplete or mislabeled.")
    for control in actual_info_controls:
        if control["aria-controls"] not in parser.ids:
            errors.append(
                "Browse-group information control has no description: "
                + control["aria-controls"]
            )

    required_links = {
        "catalog.json",
        "llms.txt",
        "https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/CONTRIBUTING.md#add-a-new-example",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
    }
    missing_links = required_links - parser.links
    if missing_links:
        errors.append("Missing required catalog links: " + ", ".join(sorted(missing_links)))
    new_tab_links = {
        "https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS": (
            "Launch NemoClaw on Brev (opens in a new tab)"
        ),
        "https://github.com/NVIDIA/nemoclaw-community": (
            "GitHub repository (opens in a new tab)"
        ),
    }
    for href, expected_label in new_tab_links.items():
        anchor = next(
            (item for item in parser.anchors if item.get("href") == href),
            None,
        )
        if anchor is None:
            errors.append(f"Missing header link: {href}")
            continue
        rel = set(anchor.get("rel", "").split())
        if anchor.get("target") != "_blank" or not {
            "noopener",
            "noreferrer",
        }.issubset(rel):
            errors.append(f"Header link must open safely in a new tab: {href}")
        if anchor.get("aria-label") != expected_label:
            errors.append(f"Header link must announce its new-tab behavior: {href}")
    if "NemoClaw Community support is best-effort" not in site_html:
        errors.append("The catalog support boundary no longer matches SUPPORT.md.")

    for relative in (
        "site/styles.css",
        "site/catalog.mjs",
        "site/assets/nvidia-logo.png",
        "site/assets/nvidia-favicon.png",
    ):
        if not is_regular_repo_file(root, root / relative):
            errors.append(f"Missing required site source: {relative}")
    css = (root / "site" / "styles.css").read_text(encoding="utf-8")
    if re.search(r"@import\b", css, flags=re.IGNORECASE):
        errors.append("CSS @import is not allowed.")
    if re.search(r"url\(\s*['\"]?(?:https?:)?//", css, flags=re.IGNORECASE):
        errors.append("Remote CSS resources are not allowed.")
    root_readme = (root / "README.md").read_text(encoding="utf-8")
    if "https://nvidia.github.io/nemoclaw-community/" not in root_readme:
        errors.append("README.md must include the published catalog URL.")
    if errors:
        raise CatalogError("\n".join(errors))


def validate_detail_pages(
    root: Path,
    entries: list[CatalogEntry],
    detail_pages: dict[str, str],
) -> None:
    expected_paths = {entry.detail_path for entry in entries}
    if set(detail_pages) != expected_paths:
        raise CatalogError("Generated detail-page paths do not match the catalog.")
    parsers: dict[str, GeneratedHTMLValidator] = {}
    for entry in entries:
        parser = GeneratedHTMLValidator()
        parser.feed(detail_pages[entry.detail_path])
        parsers[entry.detail_path] = parser

    for entry in entries:
        page = detail_pages[entry.detail_path]
        parser = parsers[entry.detail_path]
        errors = list(parser.errors)
        if parser.html_language != "en":
            errors.append("Detail page must declare html lang=\"en\".")
        if not parser.has_viewport:
            errors.append("Detail page must include a viewport meta tag.")
        if parser.h1_count != 1:
            errors.append(
                f"Detail page must contain one h1; found {parser.h1_count}."
            )
        for landmark in ("main", "footer"):
            if parser.tag_counts.get(landmark) != 1:
                errors.append(f"Detail page must contain one {landmark} landmark.")
        required_ids = {
            "detail-title",
            "facts-title",
            "maintenance-details",
            "maintenance-status-title",
            "toc-title",
            "readme",
        }
        missing_ids = required_ids - parser.ids
        if missing_ids:
            errors.append(
                "Detail page is missing required IDs: "
                + ", ".join(sorted(missing_ids))
            )
        unresolved_fragments = parser.fragments - parser.ids
        if unresolved_fragments:
            errors.append(
                "Detail page has unresolved fragments: "
                + ", ".join(sorted(unresolved_fragments))
            )
        current_dir = PurePosixPath(entry.detail_path).parent.as_posix()
        for href in parser.links:
            parts = urlsplit(href)
            if (
                not parts.fragment
                or not parts.path
                or parts.scheme
                or parts.netloc
            ):
                continue
            target_path = posixpath.normpath(
                posixpath.join(current_dir, unquote(parts.path))
            )
            if parts.path.endswith("/"):
                target_path = posixpath.join(target_path, "index.html")
            target_parser = parsers.get(target_path)
            if (
                target_parser is not None
                and unquote(parts.fragment) not in target_parser.ids
            ):
                errors.append(
                    "Detail page links to an unresolved README fragment: "
                    f"{href}"
                )
        has_mermaid = 'class="language-mermaid"' in page
        if has_mermaid:
            expected_scripts = [
                {
                    "src": _detail_relative(
                        entry, "assets/vendor/mermaid.tiny.js"
                    ),
                    "integrity": MERMAID_SRI,
                },
                {
                    "type": "module",
                    "src": _detail_relative(entry, "diagrams.mjs"),
                },
            ]
            if parser.scripts != expected_scripts:
                errors.append(
                    "Mermaid detail pages must contain only the pinned local "
                    "runtime and diagram module."
                )
            for script in expected_scripts:
                if script["src"] not in parser.resources:
                    errors.append(
                        f"Mermaid detail page is missing {script['src']}."
                    )
        elif parser.scripts:
            errors.append("Detail pages without Mermaid must not contain scripts.")
        if parser.content_security_policies != [DETAIL_CONTENT_SECURITY_POLICY]:
            errors.append("Detail page Content Security Policy changed unexpectedly.")
        expected_styles = _detail_relative(entry, "styles.css")
        expected_logo = _detail_relative(entry, "assets/nvidia-logo.png")
        expected_favicon = _detail_relative(entry, "assets/nvidia-favicon.png")
        if expected_styles not in parser.resources:
            errors.append("Detail page is missing the shared stylesheet.")
        if expected_logo not in parser.resources:
            errors.append("Detail page is missing the local NVIDIA logo.")
        if expected_favicon not in parser.resources:
            errors.append("Detail page is missing the local NVIDIA favicon.")
        required_links = {
            entry.guide_url,
            _detail_relative(entry, "index.html"),
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
        }
        if entry.upstream_url:
            required_links.add(entry.upstream_url)
        missing_links = required_links - parser.links
        if missing_links:
            errors.append(
                "Detail page is missing required links: "
                + ", ".join(sorted(missing_links))
            )
        if "NemoClaw Community support is best-effort" not in page:
            errors.append("Detail-page support text no longer matches SUPPORT.md.")
        if entry.maintenance is None or (
            f'data-maintenance="{entry.maintenance.id}"' not in page
            or entry.maintenance.explanation not in html.unescape(page)
            or '<dt id="maintenance-status-title">Maintenance</dt>' not in page
            or '<details class="maintenance-info">' not in page
            or 'class="maintenance-banner"' in page
        ):
            errors.append(
                "Detail page is missing its At-a-glance maintenance status."
            )
        if ">Fit<" in page or ">Fit:" in page:
            errors.append("Detail page still exposes the ambiguous Fit label.")
        if errors:
            raise CatalogError(
                f"Invalid generated detail page for {entry.title}:\n"
                + "\n".join(errors)
            )

    if any('class="language-mermaid"' in page for page in detail_pages.values()):
        for relative in (
            "site/diagrams.mjs",
            "site/assets/vendor/mermaid-LICENSE.txt",
        ):
            if not is_regular_repo_file(root, root / relative):
                raise CatalogError(f"Missing required diagram source: {relative}")


def verified_mermaid_asset(root: Path) -> Path:
    """Return the pinned Mermaid bundle only when its local cache is trustworthy."""

    asset = root / MERMAID_CACHE_PATH
    if (
        not is_regular_repo_file(root, asset)
    ):
        raise CatalogError(
            "The pinned Mermaid browser asset is missing. Run "
            "`python3 scripts/fetch_catalog_assets.py`."
        )
    digest = hashlib.sha256()
    with asset.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MERMAID_SHA256:
        raise CatalogError(
            f"The cached Mermaid {MERMAID_VERSION} asset failed its SHA-256 "
            "check. Run `python3 scripts/fetch_catalog_assets.py` to replace it."
        )
    return asset


@dataclass(frozen=True)
class CatalogOutputs:
    entries: list[CatalogEntry]
    categories: tuple[Category, ...]
    collections: tuple[Collection, ...]
    readme: str
    discovery_readmes: dict[str, str]
    site_html: str
    catalog_json: str
    llms_txt: str
    detail_pages: dict[str, str]
    copied_assets: set[str]
    maintenance_policy: MaintenancePolicy
    maintenance_snapshot: MaintenanceSnapshot
    as_of: dt.date


def expected_outputs(
    root: Path,
    maintenance_releases_path: Path | None = None,
    as_of: dt.date | None = None,
) -> CatalogOutputs:
    categories, collections = load_discovery_groups(root)
    policy = load_maintenance_policy(root)
    snapshot = load_maintenance_snapshot(root, policy, maintenance_releases_path)
    as_of = as_of or catalog_as_of_date()
    entries = enrich_catalog_maintenance(
        root,
        load_catalog(root, categories, collections),
        policy,
        snapshot,
        as_of,
    )
    template_path = root / "site" / "index.template.html"
    detail_template_path = root / "site" / "detail.template.html"
    try:
        template = template_path.read_text(encoding="utf-8")
        detail_template = detail_template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogError(f"Unable to read site templates: {error}") from error
    rendered_readme = render_readme(entries, categories, collections)
    rendered_discovery_readmes = render_discovery_readmes(
        entries, categories, collections
    )
    rendered_site = render_site(entries, categories, collections, template)
    rendered_json = json.dumps(
        public_catalog(entries, categories, collections, policy, snapshot, as_of),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    rendered_llms = render_llms(entries)
    detail_pages, copied_assets = render_detail_pages(root, entries, detail_template)
    validate_generated_site(
        root, entries, categories, collections, rendered_site
    )
    validate_detail_pages(root, entries, detail_pages)
    if any('class="language-mermaid"' in page for page in detail_pages.values()):
        verified_mermaid_asset(root)
    return CatalogOutputs(
        entries=entries,
        categories=categories,
        collections=collections,
        readme=rendered_readme,
        discovery_readmes=rendered_discovery_readmes,
        site_html=rendered_site,
        catalog_json=rendered_json,
        llms_txt=rendered_llms,
        detail_pages=detail_pages,
        copied_assets=copied_assets,
        maintenance_policy=policy,
        maintenance_snapshot=snapshot,
        as_of=as_of,
    )


def check_catalog(root: Path) -> list[CatalogEntry]:
    outputs = expected_outputs(root)
    check_generated_readmes(root, outputs)
    return outputs.entries


def check_generated_readmes(root: Path, outputs: CatalogOutputs) -> None:
    """Require the root and browse-group indexes to match generated membership."""

    readme_path = root / "examples" / "README.md"
    actual_readme = readme_path.read_text(encoding="utf-8")
    if actual_readme != outputs.readme:
        raise CatalogError(
            "examples/README.md is out of date. Run "
            "`python3 scripts/build_catalog.py --write`."
        )
    stale_group_readmes = [
        path
        for path, expected in outputs.discovery_readmes.items()
        if (root / path).read_text(encoding="utf-8") != expected
    ]
    if stale_group_readmes:
        raise CatalogError(
            "Browse-group README membership is out of date: "
            + ", ".join(stale_group_readmes)
            + ". Run `python3 scripts/build_catalog.py --write`."
        )


def write_readmes(root: Path, outputs: CatalogOutputs) -> None:
    (root / "examples" / "README.md").write_text(outputs.readme, encoding="utf-8")
    for path, content in outputs.discovery_readmes.items():
        (root / path).write_text(content, encoding="utf-8")


def build_site(
    root: Path,
    output: Path,
    site_html: str,
    catalog_json: str,
    llms_txt: str = "",
    detail_pages: dict[str, str] | None = None,
    copied_assets: set[str] | None = None,
) -> None:
    output = output.absolute()
    expected_output = root.resolve() / "_site"
    if output != expected_output:
        raise CatalogError("Catalog output is restricted to the generated _site directory.")
    if output.is_symlink():
        raise CatalogError("Refusing to replace a symlinked _site directory.")
    shared_files = (
        root / "site" / "styles.css",
        root / "site" / "catalog.mjs",
    )
    for source in shared_files:
        if not is_regular_repo_file(root, source):
            raise CatalogError(
                f"Catalog site source must be a regular repository file: "
                f"{source.relative_to(root)}"
            )
    site_assets = root / "site" / "assets"
    if (
        path_uses_symlink(root, site_assets)
        or not site_assets.is_dir()
        or not site_assets.resolve().is_relative_to(root.resolve())
    ):
        raise CatalogError("Catalog site assets must be a regular repository directory.")
    for asset in site_assets.rglob("*"):
        if path_uses_symlink(root, asset) or not (asset.is_file() or asset.is_dir()):
            raise CatalogError(
                "Catalog site asset must not use a symlink or special file: "
                f"{asset.relative_to(root)}"
            )
    has_mermaid = any(
        'class="language-mermaid"' in page
        for page in (detail_pages or {}).values()
    )
    mermaid_asset: Path | None = None
    diagram_module: Path | None = None
    if has_mermaid:
        mermaid_asset = verified_mermaid_asset(root)
        diagram_module = root / "site" / "diagrams.mjs"
        if not diagram_module.is_file():
            raise CatalogError("Mermaid diagram module is not a regular file.")
        if diagram_module.is_symlink():
            raise CatalogError("Mermaid diagram module must not be a symlink.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "index.html").write_text(site_html, encoding="utf-8")
    (output / "catalog.json").write_text(catalog_json, encoding="utf-8")
    (output / "llms.txt").write_text(llms_txt, encoding="utf-8")
    shutil.copy2(shared_files[0], output / "styles.css")
    shutil.copy2(shared_files[1], output / "catalog.mjs")
    shutil.copytree(site_assets, output / "assets")
    if has_mermaid:
        assert mermaid_asset is not None
        assert diagram_module is not None
        vendor_directory = output / "assets" / "vendor"
        vendor_directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            mermaid_asset,
            vendor_directory / "mermaid.tiny.js",
        )
        shutil.copy2(diagram_module, output / "diagrams.mjs")
    for relative, content in (detail_pages or {}).items():
        destination = output / relative
        if not destination.absolute().is_relative_to(output):
            raise CatalogError(f"Detail output escapes _site: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    total_asset_size = 0
    for relative in sorted(copied_assets or set()):
        source = root / relative
        resolved_source = source.resolve()
        if not is_regular_repo_file(root, source):
            raise CatalogError(
                f"README asset must be a regular repository file without symlinks: "
                f"{relative}"
            )
        total_asset_size += resolved_source.stat().st_size
        if total_asset_size > 20 * 1024 * 1024:
            raise CatalogError("README assets exceed the 20 MiB catalog limit.")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_source, destination)


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate without writing files.")
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate examples/README.md and build the site.",
    )
    mode.add_argument(
        "--validate-metadata",
        action="store_true",
        help="Validate example README catalog blocks without building the site.",
    )
    mode.add_argument(
        "--print-taxonomy",
        action="store_true",
        help="Print the generated browser taxonomy contract as JSON.",
    )
    parser.add_argument(
        "--maintenance-releases",
        type=Path,
        help=(
            "Use a validated release snapshot inside the repository instead of "
            "scripts/catalog-maintenance-releases.json."
        ),
    )
    parser.add_argument(
        "--as-of",
        help="Calculate maintenance status on this YYYY-MM-DD date.",
    )
    args = parser.parse_args(argv)
    root = find_repo_root()
    output = root / "_site"

    try:
        if args.print_taxonomy:
            print(json.dumps(taxonomy_contract(), ensure_ascii=False))
            return 0
        if args.validate_metadata:
            entries = load_catalog(root)
            print(
                f"README catalog metadata is valid for {len(entries)} examples."
            )
            return 0
        outputs = expected_outputs(
            root,
            args.maintenance_releases,
            catalog_as_of_date(args.as_of),
        )
        if args.check:
            check_generated_readmes(root, outputs)
            print(
                f"Catalog metadata and generated sources are valid: "
                f"{len(outputs.entries)} examples across "
                f"{len(outputs.categories) + len(outputs.collections)} browse groups."
            )
            return 0
        if args.write:
            write_readmes(root, outputs)
        else:
            check_generated_readmes(root, outputs)
        build_site(
            root,
            output,
            outputs.site_html,
            outputs.catalog_json,
            outputs.llms_txt,
            outputs.detail_pages,
            outputs.copied_assets,
        )
        print(
            f"Built {len(outputs.entries)} catalog entries and detail pages in "
            f"{output.relative_to(root)}."
        )
        return 0
    except (CatalogError, OSError) as error:
        print(f"Catalog build failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
