# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Discover examples and parse their canonical README metadata."""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import replace
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

try:
    from scripts.catalog_maintenance import (
        LIFECYCLES,
        MaintenancePolicyError,
        compute_status,
        load_policy,
    )
    from scripts.example_stack_facts import (
        extract_example_stack_facts,
        parse_stack_declaration,
    )
except ModuleNotFoundError:  # Support direct execution via scripts/build_catalog.py.
    from catalog_maintenance import (  # type: ignore[no-redef]
        LIFECYCLES,
        MaintenancePolicyError,
        compute_status,
        load_policy,
    )
    from example_stack_facts import (  # type: ignore[no-redef]
        extract_example_stack_facts,
        parse_stack_declaration,
    )

from .model import (
    CATEGORY_DEFINITION_BY_ID,
    CATEGORY_DEFINITIONS,
    COLLECTION_DEFINITION_BY_VALUE,
    COLLECTION_DEFINITIONS,
    INDUSTRY_EMOJIS,
    CatalogEntry,
    CatalogError,
    Category,
    Collection,
    slugify,
)


PATH_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


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
    elif len(parts) == 3 and parts[:2] == ("demos", "build-a-claw"):
        category_id = "build-a-claw-demos"
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
        allowed_demo_roots = {"build-a-claw", "field"}
        unexpected_demo_roots = {
            child.name
            for child in demos.iterdir()
            if child.is_dir() and child.name not in allowed_demo_roots
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
                "Unexpected collection directories: "
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
                    "Collection directories may contain only README.md: "
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
        "demos/build-a-claw/*",
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


def discover_tutorial_path(root: Path, path: str) -> str | None:
    """Return an example's optional, conventionally named tutorial source."""

    directory = root / "examples" / path
    tutorial = directory / "tutorial.md"
    case_variants = [
        candidate
        for candidate in directory.iterdir()
        if candidate.name.casefold() == "tutorial.md"
        and candidate.name != "tutorial.md"
    ]
    if case_variants:
        raise CatalogError(
            "Tutorial source must be named exactly `tutorial.md`: "
            + ", ".join(
                candidate.relative_to(root).as_posix()
                for candidate in sorted(case_variants)
            )
        )
    if not tutorial.exists() and not tutorial.is_symlink():
        return None
    if not is_regular_repo_file(root, tutorial):
        raise CatalogError(
            "Tutorial source must be a regular, non-symlinked repository file: "
            f"{tutorial.relative_to(root).as_posix()}"
        )
    return tutorial.relative_to(root).as_posix()


CATALOG_TABLE_HEADER = "| Catalog field | Value |"
CATALOG_TABLE_DIVIDER = "| --- | --- |"
CATALOG_METADATA_HEADING = "## Catalog Metadata"
CATALOG_FIELD_ORDER = (
    "Description",
    "Industry",
    "Requirements",
    "NemoClaw",
    "Harness",
    "OpenShell",
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
    stack_field = field in {"NemoClaw", "Harness", "OpenShell"}
    marked_up = re.search(
        r"[`*_\[\]]" if stack_field else r"[`*_~\[\]<>]",
        value,
    )
    if any(ord(character) < 32 for character in value) or (
        field != "Upstream" and marked_up
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


def parse_readme_metadata(
    root: Path,
    path: str,
    categories_by_id: dict[str, Category] | None = None,
    collections_by_value: dict[str, Collection] | None = None,
) -> CatalogEntry:
    """Parse the required human-readable metadata block from one example README."""

    category = classify_path(path, categories_by_id)
    tutorial_path = discover_tutorial_path(root, path)
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
    missing_fields = {
        "Description",
        "Industry",
        "Requirements",
        "NemoClaw",
        "Harness",
        "OpenShell",
    } - set(fields)
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

    try:
        stack_declaration = parse_stack_declaration(
            fields["NemoClaw"],
            fields["Harness"],
            fields["OpenShell"],
        )
    except ValueError as error:
        raise CatalogError(f"Invalid runtime stack metadata in {readme_path}: {error}.") from error

    lifecycle = fields.get("Lifecycle", "Active")
    if lifecycle not in LIFECYCLES:
        raise CatalogError(
            f"Lifecycle must be Active or Deprecated in {readme_path}."
        )
    reviewed: dt.date | None = None
    if reviewed_value := fields.get("Reviewed"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed_value) is None:
            raise CatalogError(f"Reviewed must use YYYY-MM-DD in {readme_path}.")
        try:
            reviewed = dt.date.fromisoformat(reviewed_value)
        except ValueError as error:
            raise CatalogError(
                f"Reviewed must be a valid calendar date in {readme_path}."
            ) from error

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
    if (
        collection_value is not None
        and collection_value not in collection_definitions
    ):
        raise CatalogError(
            f"Unknown Collection value in {readme_path}: {collection_value!r}."
        )
    if collection_value is not None and category.kind != "recipe":
        raise CatalogError("Only recipes can declare a Collection row.")
    collections = tuple(
        collection
        for collection in collection_definitions.values()
        if collection.metadata_value == collection_value
        or category.id in collection.automatic_category_ids
    )

    return CatalogEntry(
        path=path,
        title=title,
        description=description,
        industry=industry,
        requirements=requirements,
        collections=collections,
        category=category,
        contributor=contributor,
        upstream_url=upstream_url,
        readme_body=readme_body,
        tutorial_path=tutorial_path,
        lifecycle=lifecycle,
        reviewed=reviewed,
        stack_declaration=stack_declaration,
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


def latest_committed_activity(root: Path, entry: CatalogEntry) -> dt.date | None:
    """Return the last committed change date for one example."""

    if not (root / ".git").exists():
        raise CatalogError(
            "Catalog maintenance status requires Git history; build from a "
            "full Git checkout."
        )

    def run_git(arguments: list[str], operation: str) -> str:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CatalogError(
                f"Unable to {operation} for {entry.path}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"git exited {result.returncode}"
            raise CatalogError(
                f"Unable to {operation} for {entry.path}: {detail}"
            )
        return result.stdout.strip()

    relative_path = f"examples/{entry.path}"
    value = run_git(
        ["log", "-1", "--format=%ct", "--", relative_path],
        "read committed activity",
    )
    if not value:
        status = run_git(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                relative_path,
            ],
            "inspect uncommitted activity",
        )
        if status:
            return None
        raise CatalogError(
            f"No Git history found for {entry.path}; use a full-history checkout."
        )
    try:
        return dt.datetime.fromtimestamp(
            int(value), tz=dt.timezone.utc
        ).date()
    except (OSError, OverflowError, ValueError) as error:
        raise CatalogError(
            f"Git returned an invalid activity timestamp for {entry.path}: {value!r}."
        ) from error


def enrich_catalog(
    root: Path,
    entries: list[CatalogEntry],
    *,
    today: dt.date | None = None,
    activity_dates: dict[str, dt.date] | None = None,
) -> list[CatalogEntry]:
    """Add read-only runtime stack facts and computed maintenance status."""

    current_day = today or dt.datetime.now(dt.timezone.utc).date()
    policy_path = root / "scripts" / "catalog-maintenance.json"
    try:
        policy = load_policy(policy_path) if policy_path.is_file() else load_policy()
        enriched: list[CatalogEntry] = []
        for entry in entries:
            committed_on = (
                activity_dates.get(entry.path)
                if activity_dates is not None and entry.path in activity_dates
                else latest_committed_activity(root, entry)
            )
            # A newly added, uncommitted example uses the build date for preview.
            committed_on = committed_on or current_day
            if entry.stack_declaration is None:
                raise CatalogError(f"Missing runtime stack declaration for {entry.path}.")
            try:
                stack = extract_example_stack_facts(
                    root / "examples" / entry.path,
                    entry.stack_declaration,
                )
            except (OSError, ValueError) as error:
                raise CatalogError(f"Invalid runtime stack contract: {error}") from error
            maintenance = compute_status(
                policy,
                committed_on=committed_on,
                reviewed_on=entry.reviewed,
                today=current_day,
                lifecycle=entry.lifecycle,
            )
            enriched.append(
                replace(
                    entry,
                    last_activity=committed_on,
                    stack=stack,
                    maintenance=maintenance,
                )
            )
        return enriched
    except MaintenancePolicyError as error:
        raise CatalogError(f"Invalid catalog maintenance policy: {error}") from error
