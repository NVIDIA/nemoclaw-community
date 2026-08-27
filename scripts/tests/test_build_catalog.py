# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for structured catalog metadata and generation."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.build_catalog import (
    CatalogError,
    MERMAID_SHA256,
    MERMAID_VERSION,
    build_site,
    check_catalog,
    expected_outputs,
    extract_mermaid_sources,
    load_catalog,
    public_catalog,
    render_detail_pages,
    render_readme_html,
    validate_detail_pages,
)
from scripts.fetch_catalog_assets import (
    MERMAID_SHA256 as FETCHED_MERMAID_SHA256,
    MERMAID_VERSION as FETCHED_MERMAID_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]


class CatalogBuildTests(unittest.TestCase):
    def _fixture_root(self, record: dict[str, object] | None = None) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        example = root / "examples" / "recipes" / "community" / "sample"
        example.mkdir(parents=True)
        (example / "README.md").write_text(
            "# Sample Example\n\nA small fixture.\n", encoding="utf-8"
        )
        shutil.copy2(
            ROOT / "examples" / "catalog.schema.json",
            root / "examples" / "catalog.schema.json",
        )
        source_record: dict[str, object] = {
            "path": "recipes/community/sample",
            "title": "Sample Example",
            "description": "Produces a small observable fixture result.",
            "industry": "Other",
            "requirements": "Python 3 · local/static",
            "collections": [],
        }
        if record:
            source_record.update(record)
        manifest = {
            "$schema": "catalog.schema.json",
            "schema_version": 2,
            "examples": [source_record],
        }
        (root / "examples" / "catalog.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return root

    def _rewrite_manifest(self, root: Path, mutate) -> None:
        path = root / "examples" / "catalog.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        mutate(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_mermaid_fetch_and_build_pins_match(self) -> None:
        self.assertEqual(MERMAID_VERSION, FETCHED_MERMAID_VERSION)
        self.assertEqual(MERMAID_SHA256, FETCHED_MERMAID_SHA256)

    def test_current_catalog_and_generated_markdown_are_valid(self) -> None:
        entries = check_catalog(ROOT)

        self.assertGreater(len(entries), 0)
        index = public_catalog(entries)
        self.assertEqual(
            sum(category["count"] for category in index["categories"]),
            len(entries),
        )
        self.assertEqual(
            sum(industry["count"] for industry in index["industries"]),
            len(entries),
        )

    def test_path_derives_kind_and_recipe_provenance(self) -> None:
        entry = load_catalog(self._fixture_root())[0]

        self.assertEqual(entry.category.kind, "recipe")
        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.industry, "Other")

    def test_unknown_industry_is_rejected(self) -> None:
        root = self._fixture_root({"industry": "Software"})

        with self.assertRaisesRegex(CatalogError, "documented values"):
            load_catalog(root)

    def test_non_kebab_case_catalog_path_is_rejected(self) -> None:
        root = self._fixture_root({"path": "recipes/community/Bad Name"})

        with self.assertRaisesRegex(CatalogError, "canonical example taxonomy"):
            load_catalog(root)

    def test_unlisted_top_level_example_is_rejected(self) -> None:
        root = self._fixture_root()
        unlisted = root / "examples" / "tools" / "unlisted"
        unlisted.mkdir(parents=True)
        (unlisted / "README.md").write_text("# Unlisted\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "missing from examples/catalog.json"):
            load_catalog(root)

    def test_partner_recipe_requires_contributor(self) -> None:
        root = self._fixture_root()
        old = root / "examples" / "recipes" / "community" / "sample"
        new = root / "examples" / "recipes" / "partners" / "acme" / "sample"
        new.parent.mkdir(parents=True)
        old.rename(new)
        self._rewrite_manifest(
            root,
            lambda manifest: manifest["examples"][0].update(
                {"path": "recipes/partners/acme/sample"}
            ),
        )

        with self.assertRaisesRegex(CatalogError, "requires contributor"):
            load_catalog(root)

    def test_hackathon_collection_does_not_replace_provenance(self) -> None:
        entry = load_catalog(self._fixture_root({"collections": ["hackathon"]}))[0]

        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.collections, ("hackathon",))

    def test_public_index_exposes_orthogonal_facets(self) -> None:
        entries = load_catalog(self._fixture_root())
        index = public_catalog(entries)
        example = index["examples"][0]

        self.assertEqual(example["kind"], "recipe")
        self.assertEqual(example["provenance"], "community")
        self.assertEqual(example["industry"]["id"], "other")
        self.assertEqual(example["collections"], [])
        self.assertEqual(example["requirements"], "Python 3 · local/static")
        self.assertEqual(
            example["detail_url"], "examples/recipes/community/sample/"
        )

    def test_current_catalog_compiles_one_safe_detail_page_per_example(self) -> None:
        entries, _, _, _, detail_pages, copied_assets = expected_outputs(ROOT)

        self.assertEqual(len(detail_pages), len(entries))
        self.assertEqual(set(detail_pages), {entry.detail_path for entry in entries})
        self.assertTrue(copied_assets)
        mermaid_pages = 0
        mermaid_diagrams = 0
        for entry in entries:
            page = detail_pages[entry.detail_path]
            self.assertEqual(page.count("<h1"), 1)
            self.assertIn("Requirements &amp; limits", page)
            self.assertIn('id="readme" tabindex="-1"', page)
            self.assertNotRegex(page, r'<(?:iframe|object|embed)\b')
            self.assertNotRegex(page, r'<img[^>]+src="https?://')
            diagram_count = page.count('class="language-mermaid"')
            source = (ROOT / entry.readme_path).read_text(encoding="utf-8")
            expected_diagram_count = len(
                extract_mermaid_sources(source, entry.readme_path)
            )
            self.assertEqual(diagram_count, expected_diagram_count)
            mermaid_diagrams += diagram_count
            if diagram_count:
                mermaid_pages += 1
                self.assertIn("mermaid.tiny.js", page)
                self.assertIn('type="module"', page)
                self.assertIn("diagrams.mjs", page)
            else:
                self.assertNotIn("<script", page)
        self.assertGreater(mermaid_pages, 0)
        self.assertGreater(mermaid_diagrams, 0)

    def test_readme_compiler_rejects_unsafe_mermaid(self) -> None:
        unsafe_sources = {
            "unsupported type": "pie\n    title Unsafe",
            "configuration directive": (
                "flowchart LR\n"
                "    %%{init: {'theme': 'dark'}}%%\n"
                "    A --> B"
            ),
            "click directive": (
                "flowchart LR\n"
                "    A --> B\n"
                "    click A href 'https://example.com'"
            ),
            "inline click directive": (
                "flowchart LR\n"
                "    A --> B; click A 'https://example.com'"
            ),
            "remote image shape": (
                "flowchart LR\n"
                '    A@{ img: "https://example.com/image.png" }'
            ),
            "active HTML": "graph TD\n    A[<script>alert(1)</script>]",
        }
        for case, diagram in unsafe_sources.items():
            with self.subTest(case=case):
                root = self._fixture_root()
                readme = (
                    root
                    / "examples"
                    / "recipes"
                    / "community"
                    / "sample"
                    / "README.md"
                )
                readme.write_text(
                    f"# Sample Example\n\n```mermaid\n{diagram}\n```\n",
                    encoding="utf-8",
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_allows_plain_text_mermaid_labels(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "sample" / "README.md"
        readme.write_text(
            "# Sample Example\n\n"
            "```mermaid\n"
            "graph LR\n"
            "    A[Data: customer records] --> B[Metadata: status]\n"
            "    B --> C[JavaScript: browser client]\n"
            "```\n",
            encoding="utf-8",
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

    def test_readme_compiler_rejects_active_raw_html(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "sample" / "README.md"
        readme.write_text(
            "# Sample Example\n\n<script>alert('unsafe')</script>\n",
            encoding="utf-8",
        )
        entry = load_catalog(root)[0]

        with self.assertRaisesRegex(CatalogError, "Unsupported README HTML element"):
            render_readme_html(
                root,
                entry,
                {entry.readme_path: entry},
                set(),
            )

    def test_readme_compiler_rejects_unsafe_links(self) -> None:
        unsafe_links = (
            "http://example.com",
            "//example.com/path",
            "javascript:alert(1)",
            "data:text/html,unsafe",
            "../../../../../outside",
        )
        for destination in unsafe_links:
            with self.subTest(destination=destination):
                root = self._fixture_root()
                readme = (
                    root / "examples" / "recipes" / "community" / "sample" / "README.md"
                )
                readme.write_text(
                    f"# Sample Example\n\n[Unsafe link]({destination})\n",
                    encoding="utf-8",
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_rejects_unsafe_image_assets(self) -> None:
        for case in ("svg", "symlink", "oversized"):
            with self.subTest(case=case):
                root = self._fixture_root()
                example = root / "examples" / "recipes" / "community" / "sample"
                assets = example / "assets"
                assets.mkdir()
                if case == "svg":
                    asset = assets / "unsafe.svg"
                    asset.write_text(
                        '<svg xmlns="http://www.w3.org/2000/svg" '
                        'xmlns:s="http://www.w3.org/2000/svg">'
                        '<s:script>alert(1)</s:script></svg>',
                        encoding="utf-8",
                    )
                elif case == "symlink":
                    source = root / "source.png"
                    source.write_bytes(b"png")
                    asset = assets / "unsafe.png"
                    asset.symlink_to(source)
                else:
                    asset = assets / "unsafe.png"
                    asset.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
                (example / "README.md").write_text(
                    f"# Sample Example\n\n![Unsafe image](assets/{asset.name})\n",
                    encoding="utf-8",
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_rejects_missing_fragments(self) -> None:
        root = self._fixture_root()
        example = root / "examples" / "recipes" / "community" / "sample"
        (example / "README.md").write_text(
            "# Sample Example\n\n[Missing](README.md#not-present)\n",
            encoding="utf-8",
        )
        entry = load_catalog(root)[0]
        with self.assertRaisesRegex(CatalogError, "unresolved local fragments"):
            render_readme_html(root, entry, {entry.readme_path: entry}, set())

        target = root / "examples" / "recipes" / "community" / "target"
        target.mkdir()
        (target / "README.md").write_text(
            "# Target Example\n\n## Present\n", encoding="utf-8"
        )
        (example / "README.md").write_text(
            "# Sample Example\n\n[Missing](../target/README.md#not-present)\n",
            encoding="utf-8",
        )
        self._rewrite_manifest(
            root,
            lambda manifest: manifest["examples"].append(
                {
                    "path": "recipes/community/target",
                    "title": "Target Example",
                    "description": "Provides a second observable fixture result.",
                    "industry": "Other",
                    "requirements": "Python 3 · local/static",
                    "collections": [],
                }
            ),
        )
        entries = load_catalog(root)
        template = (ROOT / "site" / "detail.template.html").read_text(encoding="utf-8")
        pages, _ = render_detail_pages(root, entries, template)

        with self.assertRaisesRegex(CatalogError, "unresolved README fragment"):
            validate_detail_pages(root, entries, pages)

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


if __name__ == "__main__":
    unittest.main()
