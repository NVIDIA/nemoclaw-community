# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Coordinate validation, rendering, and publication of the static catalog."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from .detail_pages import render_detail_pages
from .listings import (
    public_catalog,
    render_discovery_readmes,
    render_llms,
    render_readme,
    render_site,
)
from .model import CatalogEntry, CatalogError, CatalogOutputs
from .sources import (
    enrich_catalog,
    is_regular_repo_file,
    load_catalog,
    load_discovery_groups,
    path_uses_symlink,
)
from .validation import (
    validate_detail_pages,
    validate_generated_site,
    verified_mermaid_asset,
)


def expected_outputs(
    root: Path,
    *,
    today: dt.date | None = None,
    activity_dates: dict[str, dt.date] | None = None,
) -> CatalogOutputs:
    categories, collections = load_discovery_groups(root)
    entries = load_catalog(root, categories, collections)
    entries = enrich_catalog(
        root,
        entries,
        today=today,
        activity_dates=activity_dates,
    )
    template_path = root / "site" / "templates" / "index.html"
    detail_template_path = root / "site" / "templates" / "detail.html"
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
        public_catalog(entries, categories, collections),
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
    has_tutorial = any(
        'class="detail-page tutorial-page"' in page
        for page in (detail_pages or {}).values()
    )
    shared_files = {
        "styles/shared.css": root / "site" / "styles" / "shared.css",
        "styles/catalog.css": root / "site" / "styles" / "catalog.css",
        "styles/detail.css": root / "site" / "styles" / "detail.css",
        "scripts/catalog-state.mjs": (
            root / "site" / "scripts" / "catalog-state.mjs"
        ),
        "scripts/catalog.mjs": root / "site" / "scripts" / "catalog.mjs",
    }
    if has_tutorial:
        shared_files.update(
            {
                "styles/tutorial.css": (
                    root / "site" / "styles" / "tutorial.css"
                ),
                "scripts/tutorial.mjs": (
                    root / "site" / "scripts" / "tutorial.mjs"
                ),
            }
        )
    for source in shared_files.values():
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
        diagram_module = root / "site" / "scripts" / "diagrams.mjs"
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
    for destination, source in shared_files.items():
        destination_path = output / destination
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination_path)
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
        diagram_destination = output / "scripts" / "diagrams.mjs"
        diagram_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(diagram_module, diagram_destination)
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
