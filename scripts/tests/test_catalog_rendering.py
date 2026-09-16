# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for catalog listing, Markdown, and detail-page rendering."""

from __future__ import annotations

import unittest

from scripts.catalog.detail_pages import render_detail_pages
from scripts.catalog.listings import (
    category_filter_options,
    public_catalog,
    render_catalog_groups,
    render_category_nav,
    render_discovery_readmes,
    render_industry_nav,
    render_llms,
)
from scripts.catalog.markdown import render_readme_html
from scripts.catalog.model import PAGES_BASE_URL
from scripts.catalog.sources import load_catalog, load_discovery_groups

from scripts.tests.catalog_test_support import CatalogFixtureMixin, ROOT


class CatalogRenderingTests(CatalogFixtureMixin, unittest.TestCase):
    def test_browse_group_metadata_drives_navigation_json_and_indexes(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "README.md"
        content = readme.read_text(encoding="utf-8").replace(
            "Describes the Community Recipes browse group for fixture tests.",
            "A distinctive community description from the README source.",
        )
        readme.write_text(content, encoding="utf-8")
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)

        navigation = render_category_nav(entries, categories, collections)
        self.assertIn("A distinctive community description", navigation)
        self.assertIn("Build-a-Claw", navigation)
        self.assertIn('data-empty="true"', navigation)
        index = public_catalog(entries, categories, collections)
        community = next(
            category
            for category in index["categories"]
            if category["id"] == "community-recipes"
        )
        self.assertEqual(
            community["description"],
            "A distinctive community description from the README source.",
        )
        group_readmes = render_discovery_readmes(
            entries, categories, collections
        )
        community_readme = group_readmes[
            "examples/recipes/community/README.md"
        ]
        self.assertIn(
            "[Sample Example](sample/README.md)",
            community_readme,
        )
        self.assertIn(
            "A distinctive community description from the README source.\n\n"
            "## Examples\n\n| Example | Industry | Description |",
            community_readme,
        )
        self.assertIn(
            "_No examples are currently in this group._",
            group_readmes["examples/collections/build-a-claw/README.md"],
        )
        self.assertEqual(
            sum(industry["count"] for industry in index["industries"]),
            len(entries),
        )

    def test_build_a_claw_has_one_combined_website_browse_group(self) -> None:
        root = self._fixture_root(
            {
                "path": "demos/field/build-a-claw-tutorial",
                "collection": "Build-a-Claw",
            }
        )
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)

        navigation = render_category_nav(entries, categories, collections)
        options = category_filter_options(entries, categories, collections)
        groups = render_catalog_groups(entries, categories)
        self.assertEqual(navigation.count("?category=build-a-claw#catalog"), 1)
        self.assertNotIn("?category=build-a-claw-demos", navigation)
        self.assertNotIn("?category=build-a-claw-recipes", navigation)
        self.assertEqual(options.count('value="build-a-claw"'), 1)
        self.assertNotIn('value="build-a-claw-demos"', options)
        self.assertNotIn('value="build-a-claw-recipes"', options)
        self.assertLess(
            navigation.index('?category=build-a-claw#catalog'),
            navigation.index('?category=hackathon-recipes#catalog'),
        )
        self.assertLess(
            options.index('value="build-a-claw"'),
            options.index('value="hackathon-recipes"'),
        )
        self.assertIn(
            '<div class="category-tile" data-empty="false">\n'
            '  <a class="category-tile-link" '
            'href="?category=build-a-claw#catalog">',
            navigation,
        )
        self.assertIn(
            '<span class="category-name">Build-a-Claw</span>', navigation
        )
        self.assertIn(">NVIDIA Field Demos</h2>", groups)
        self.assertNotIn(">Build-a-Claw Demos</h2>", groups)

        index = public_catalog(entries, categories, collections)
        build_a_claw = next(
            collection
            for collection in index["collections"]
            if collection["id"] == "build-a-claw"
        )
        self.assertEqual(build_a_claw["count"], 1)
        self.assertEqual(index["examples"][0]["collections"], ["build-a-claw"])

    def test_tutorial_md_uses_one_authored_markdown_source(self) -> None:
        root = self._fixture_root()
        tutorial = root / "examples/recipes/community/sample/tutorial.md"
        source = (
            b"# Authored Tutorial\n\n[TOC]\n\n# Part One\n\n## First Step\n\n"
            b"```text\n# Preserved in code\n[TOC]\n```\n\n"
            b"```bash\necho \"$HOME\" # highlighted command\n```\n\n"
            b"![Remote image](https://images.example.com/tutorial.png)\n\n"
            b'<iframe src="https://www.youtube.com/embed/video" '
            b'title="Tutorial video" allowfullscreen></iframe>\n'
        )
        tutorial.write_bytes(source)

        entry = load_catalog(root)[0]
        title, body, toc, _ = render_readme_html(
            root, entry, {entry.readme_path: entry}, set()
        )

        self.assertTrue(entry.is_tutorial)
        self.assertEqual(entry.content_path, entry.tutorial_path)
        self.assertEqual(title, "Authored Tutorial")
        self.assertIn('<h2 id="part-one">Part One</h2>', body)
        self.assertIn('<h3 id="first-step">First Step</h3>', body)
        self.assertIn("# Preserved in code", body)
        self.assertIn('<code class="language-text">', body)
        self.assertIn('<code class="language-bash">', body)
        self.assertIn('<span class="nb">echo</span>', body)
        self.assertNotIn('<div class="toc">', body)
        self.assertIn('href="#first-step"', toc)
        self.assertNotIn('src="https://images.example.com/tutorial.png"', body)
        self.assertIn(
            'class="readme-image-link" '
            'href="https://images.example.com/tutorial.png" rel="noreferrer"',
            body,
        )
        self.assertIn("View external image from images.example.com", body)
        self.assertIn('src="https://www.youtube.com/embed/video"', body)
        self.assertEqual(tutorial.read_bytes(), source)

    def test_tutorial_detail_keeps_at_a_glance_before_commands(self) -> None:
        root = self._fixture_root()
        tutorial = root / "examples/recipes/community/sample/tutorial.md"
        tutorial.write_text(
            "# Tutorial\n\n# Start\n\n```bash\necho ready\n```\n",
            encoding="utf-8",
        )
        entry = load_catalog(root)[0]
        template = (ROOT / "site" / "templates" / "detail.html").read_text(
            encoding="utf-8"
        )

        pages, _ = render_detail_pages(root, [entry], template)
        page = pages[entry.detail_path]
        facts_start = page.index('<aside class="detail-facts"')
        facts_open = page[facts_start : page.index(">", facts_start)]

        self.assertNotIn("hidden", facts_open)
        self.assertIn("Requirements &amp; limits", page)
        self.assertLess(facts_start, page.index('<article class="readme-content'))

    def test_industry_navigation_wraps_slash_labels_at_word_boundaries(self) -> None:
        entries = load_catalog(
            self._fixture_root({"industry": "Automotive/Transportation"})
        )

        self.assertIn(
            "Automotive/<wbr>Transportation",
            render_industry_nav(entries),
        )

    def test_public_index_exposes_orthogonal_facets(self) -> None:
        root = self._fixture_root()
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)
        index = public_catalog(entries, categories, collections)
        example = index["examples"][0]

        self.assertEqual(example["kind"], "recipe")
        self.assertEqual(example["provenance"], "community")
        self.assertEqual(example["industry"]["id"], "other")
        self.assertEqual(example["industry"]["emoji"], "✨")
        self.assertEqual(example["collections"], [])
        self.assertIsNone(example["upstream_url"])
        self.assertNotIn("environment", example)
        self.assertEqual(
            example["description"],
            "Produces a small observable fixture result.",
        )
        self.assertEqual(example["requirements"], "Python 3 · local/static")
        self.assertEqual(example["lifecycle"], "Active")
        self.assertIsNone(example["stack"])
        self.assertIsNone(example["maintenance"])
        self.assertEqual(
            example["detail_url"], "examples/recipes/community/sample/"
        )

    def test_upstream_reaches_json_detail_page_and_llms_index(self) -> None:
        upstream_url = "https://example.com/upstream/project_(one)"
        root = self._fixture_root(
            {"upstream": upstream_url}
        )
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)
        index = public_catalog(entries, categories, collections)
        self.assertEqual(
            index["examples"][0]["upstream_url"],
            upstream_url,
        )

        template = (ROOT / "site" / "templates" / "detail.html").read_text(
            encoding="utf-8"
        )
        pages, _ = render_detail_pages(root, entries, template)
        page = pages[entries[0].detail_path]
        self.assertIn("Upstream project", page)
        self.assertIn(upstream_url, page)

        llms = render_llms(entries)
        self.assertIn(f"[Sample Example]({PAGES_BASE_URL}examples/", llms)
        self.assertIn(f"[Project](<{upstream_url}>)", llms)
        self.assertIn(entries[0].guide_url, llms)

    def test_readme_compiler_allows_plain_text_mermaid_labels(self) -> None:
        root = self._fixture_root(
            body=(
            "```mermaid\n"
            "graph LR\n"
            "    A[Data: customer records] --> B[Metadata: status]\n"
            "    B --> C[JavaScript: browser client]\n"
            "```\n"
            )
        )
        entry = load_catalog(root)[0]

        _, body, _, has_mermaid = render_readme_html(
            root,
            entry,
            {entry.readme_path: entry},
            set(),
        )

        self.assertTrue(has_mermaid)
        self.assertIn('class="language-mermaid"', body)


if __name__ == "__main__":
    unittest.main()
