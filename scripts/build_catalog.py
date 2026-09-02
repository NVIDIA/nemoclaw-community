#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate catalog metadata and build the static GitHub Pages catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from .catalog.listings import taxonomy_contract
    from .catalog.model import CatalogError
    from .catalog.pipeline import (
        build_site,
        check_generated_readmes,
        expected_outputs,
        write_readmes,
    )
    from .catalog.sources import load_catalog
else:
    from catalog.listings import taxonomy_contract
    from catalog.model import CatalogError
    from catalog.pipeline import (
        build_site,
        check_generated_readmes,
        expected_outputs,
        write_readmes,
    )
    from catalog.sources import load_catalog


def find_repo_root() -> Path:
    """Find the checkout root from the current working directory."""

    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
    return path


def main(argv: list[str] | None = None) -> int:
    """Run the catalog compiler command-line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Validate without writing files."
    )
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
    args = parser.parse_args(argv)
    root = find_repo_root()
    output = root / "_site"

    try:
        if args.print_taxonomy:
            print(json.dumps(taxonomy_contract(), ensure_ascii=False))
            return 0
        if args.validate_metadata:
            entries = load_catalog(root)
            print(f"README catalog metadata is valid for {len(entries)} examples.")
            return 0
        outputs = expected_outputs(root)
        if args.check:
            check_generated_readmes(root, outputs)
            browse_groups = sum(
                category.browse for category in outputs.categories
            ) + len(outputs.collections)
            print(
                f"Catalog metadata and generated sources are valid: "
                f"{len(outputs.entries)} examples across "
                f"{browse_groups} browse groups."
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
