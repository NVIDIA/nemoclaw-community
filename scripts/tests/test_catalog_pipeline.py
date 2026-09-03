# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the catalog build and publication pipeline."""

from __future__ import annotations

import html
import tempfile
import unittest
from pathlib import Path

from scripts.catalog.listings import public_catalog
from scripts.catalog.markdown import (
    MERMAID_SHA256,
    MERMAID_VERSION,
    extract_mermaid_sources,
)
from scripts.catalog.model import CatalogError
from scripts.catalog.pipeline import (
    build_site,
    check_catalog,
    expected_outputs,
)
from scripts.catalog.sources import load_discovery_groups
from scripts.fetch_catalog_assets import (
    MERMAID_SHA256 as FETCHED_MERMAID_SHA256,
    MERMAID_VERSION as FETCHED_MERMAID_VERSION,
)

from scripts.tests.catalog_test_support import CatalogFixtureMixin, ROOT


class CatalogPipelineTests(CatalogFixtureMixin, unittest.TestCase):
    @staticmethod
    def _write_site_sources(site: Path) -> None:
        styles = site / "styles"
        scripts = site / "scripts"
        styles.mkdir(parents=True)
        scripts.mkdir(parents=True)
        for name in ("shared.css", "catalog.css", "detail.css"):
            (styles / name).write_text("", encoding="utf-8")
        for name in ("catalog-state.mjs", "catalog.mjs"):
            (scripts / name).write_text("", encoding="utf-8")

    def test_mermaid_fetch_and_build_pins_match(self) -> None:
        self.assertEqual(MERMAID_VERSION, FETCHED_MERMAID_VERSION)
        self.assertEqual(MERMAID_SHA256, FETCHED_MERMAID_SHA256)

    def test_current_catalog_and_generated_markdown_are_valid(self) -> None:
        entries = check_catalog(ROOT)
        categories, collections = load_discovery_groups(ROOT)

        self.assertGreater(len(entries), 0)
        index = public_catalog(entries, categories, collections)
        self.assertEqual(
            sum(category["count"] for category in index["categories"]),
            len(entries),
        )

    def test_current_catalog_compiles_one_safe_detail_page_per_example(self) -> None:
        outputs = expected_outputs(ROOT)
        entries = outputs.entries
        detail_pages = outputs.detail_pages
        copied_assets = outputs.copied_assets

        self.assertEqual(len(detail_pages), len(entries))
        self.assertEqual(set(detail_pages), {entry.detail_path for entry in entries})
        self.assertIn(
            '<link rel="icon" type="image/png" sizes="64x64" '
            'href="assets/nvidia-favicon.png">',
            outputs.site_html,
        )
        header = outputs.site_html.split('<header class="site-header">', 1)[1].split(
            "</header>", 1
        )[0]
        hero_actions = outputs.site_html.split(
            '<nav class="hero-actions"', 1
        )[1].split("</nav>", 1)[0]
        self.assertNotIn("Build-a-Claw tutorial", header)
        self.assertIn(
            '<a class="button button-tertiary" '
            'href="examples/demos/field/build-a-claw-tutorial/">',
            hero_actions,
        )
        self.assertIn("Getting Started", hero_actions)
        self.assertTrue(copied_assets)
        mermaid_pages = 0
        mermaid_diagrams = 0
        for entry in entries:
            page = detail_pages[entry.detail_path]
            self.assertEqual(page.count("<h1"), 1)
            self.assertIn(
                f'<p class="detail-summary">{html.escape(entry.description)}</p>',
                page,
            )
            self.assertIn("Requirements &amp; limits", page)
            facts_panel = page.split('<aside class="detail-facts"', 1)[1].split(
                "</aside>", 1
            )[0]
            facts_attributes = facts_panel.split(">", 1)[0]
            self.assertIn("<dt>Harness</dt>", facts_panel)
            self.assertIn("<dt>OpenShell</dt>", facts_panel)
            self.assertNotIn("<dt>NemoClaw</dt>", facts_panel)
            self.assertNotIn("<dt>Harness version</dt>", facts_panel)
            self.assertNotRegex(facts_panel, r"NemoClaw v?\d")
            self.assertEqual(
                facts_panel.count('class="status-dot" aria-hidden="true"'),
                2,
            )
            self.assertEqual(facts_panel.count('<details class="fact-info">'), 2)
            self.assertIn(
                '<summary aria-label="About stack metadata">', facts_panel
            )
            self.assertIn(
                '<summary aria-label="About maintenance status">', facts_panel
            )
            self.assertNotIn('role="tooltip"', facts_panel)
            self.assertNotIn('tabindex="0"', facts_panel)
            self.assertIn(
                "This reflects repository activity only, not support, quality, "
                "or runtime health.",
                facts_panel,
            )
            self.assertIn("Maintenance", page)
            self.assertIn(f"stack-status-{entry.stack.status}", page)
            self.assertIn(f"maintenance-tone-{entry.maintenance.tone}", page)
            self.assertNotIn("Catalog field", page)
            self.assertIn('id="readme" tabindex="-1"', page)
            if entry.is_tutorial:
                self.assertNotIn(" hidden", facts_attributes)
                self.assertRegex(page, r'<iframe\b')
                self.assertNotRegex(page, r'<img[^>]+src="https?://')
                self.assertIn('class="readme-image-link"', page)
                self.assertIn('rel="noreferrer"', page)
                self.assertIn('<div class="codehilite">', page)
                self.assertIn('<code class="language-bash">', page)
                self.assertIn("tutorial.css", page)
                self.assertIn("tutorial.mjs", page)
            else:
                self.assertNotIn(" hidden", facts_attributes)
                self.assertNotIn("tutorial.css", page)
                self.assertNotRegex(page, r'<(?:iframe|object|embed)\b')
                self.assertNotRegex(page, r'<img[^>]+src="https?://')
            self.assertRegex(
                page,
                r'<link rel="icon" type="image/png" sizes="64x64" '
                r'href="[^"]*assets/nvidia-favicon\.png">',
            )
            diagram_count = page.count('class="language-mermaid"')
            source = (ROOT / entry.content_path).read_text(encoding="utf-8")
            expected_diagram_count = len(
                extract_mermaid_sources(source, entry.content_path)
            )
            self.assertEqual(diagram_count, expected_diagram_count)
            mermaid_diagrams += diagram_count
            if diagram_count:
                mermaid_pages += 1
                self.assertIn("mermaid.tiny.js", page)
                self.assertIn('type="module"', page)
                self.assertIn("diagrams.mjs", page)
            elif not entry.is_tutorial:
                self.assertNotIn("<script", page)
        generated_index = public_catalog(
            entries,
            outputs.categories,
            outputs.collections,
        )
        self.assertEqual(generated_index["schema_version"], 4)
        self.assertTrue(
            all(example["stack"] for example in generated_index["examples"])
        )
        self.assertTrue(
            all(example["maintenance"] for example in generated_index["examples"])
        )
        self.assertGreater(mermaid_pages, 0)
        self.assertGreater(mermaid_diagrams, 0)

    def test_build_output_cannot_replace_source_or_follow_a_symlink(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        source = root / "site"
        source.mkdir()
        evidence = source / "keep.txt"
        evidence.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "restricted to"):
            build_site(root, source, "", "")

        (root / "_site").symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(CatalogError, "symlinked"):
            build_site(root, root / "_site", "", "")
        self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")

    def test_build_output_rejects_symlinked_shared_asset(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        site = root / "site"
        assets = site / "assets"
        assets.mkdir(parents=True)
        self._write_site_sources(site)
        source = root / "source.txt"
        source.write_text("must not be published", encoding="utf-8")
        (assets / "unsafe.txt").symlink_to(source)

        with self.assertRaisesRegex(CatalogError, "must not use a symlink"):
            build_site(root, root / "_site", "", "")

    def test_build_writes_llms_index_with_the_static_site(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        assets = root / "site" / "assets"
        assets.mkdir(parents=True)
        self._write_site_sources(root / "site")
        (assets / "logo.png").write_bytes(b"png")

        build_site(root, root / "_site", "<html></html>", "{}\n", "# Index\n")

        self.assertEqual(
            (root / "_site" / "llms.txt").read_text(encoding="utf-8"),
            "# Index\n",
        )
        self.assertTrue((root / "_site" / "styles" / "shared.css").is_file())
        self.assertTrue(
            (root / "_site" / "scripts" / "catalog-state.mjs").is_file()
        )
        self.assertTrue((root / "_site" / "scripts" / "catalog.mjs").is_file())


if __name__ == "__main__":
    unittest.main()
