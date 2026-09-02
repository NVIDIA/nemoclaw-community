# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for generated Markdown and detail-page safety validation."""

from __future__ import annotations

import unittest

from scripts.catalog.detail_pages import render_detail_pages
from scripts.catalog.markdown import render_readme_html
from scripts.catalog.model import CatalogError
from scripts.catalog.sources import load_catalog
from scripts.catalog.validation import validate_detail_pages

from scripts.tests.catalog_test_support import CatalogFixtureMixin, ROOT


class CatalogValidationTests(CatalogFixtureMixin, unittest.TestCase):
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
                root = self._fixture_root(
                    body=f"```mermaid\n{diagram}\n```\n"
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_rejects_active_raw_html(self) -> None:
        root = self._fixture_root(
            body="<script>alert('unsafe')</script>\n"
        )
        entry = load_catalog(root)[0]

        with self.assertRaisesRegex(CatalogError, "Unsupported README HTML element"):
            render_readme_html(
                root,
                entry,
                {entry.readme_path: entry},
                set(),
            )

    def test_tutorial_compiler_rejects_unsupported_iframes(self) -> None:
        for source in (
            "http://www.youtube.com/embed/video",
            "https://example.com/embed/video",
        ):
            with self.subTest(source=source):
                root = self._fixture_root()
                tutorial = root / "examples/recipes/community/sample/tutorial.md"
                tutorial.write_text(
                    "# Tutorial\n\n"
                    f'<iframe src="{source}" title="Video"></iframe>\n',
                    encoding="utf-8",
                )
                entry = load_catalog(root)[0]
                with self.assertRaisesRegex(
                    CatalogError, "Unsupported tutorial iframe source"
                ):
                    render_readme_html(
                        root, entry, {entry.readme_path: entry}, set()
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
                root = self._fixture_root(
                    body=f"[Unsafe link]({destination})\n"
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
        for case in ("svg", "symlink", "symlinked-parent", "oversized"):
            with self.subTest(case=case):
                root = self._fixture_root()
                example = root / "examples" / "recipes" / "community" / "sample"
                assets = example / "assets"
                if case == "symlinked-parent":
                    real_assets = example / "real-assets"
                    real_assets.mkdir()
                    asset = real_assets / "unsafe.png"
                    asset.write_bytes(b"png")
                    assets.symlink_to(real_assets, target_is_directory=True)
                else:
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
                elif case == "oversized":
                    asset = assets / "unsafe.png"
                    asset.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
                self._write_fixture_readme(
                    root,
                    "recipes/community/sample",
                    body=f"![Unsafe image](assets/{asset.name})\n",
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
        root = self._fixture_root(body="[Missing](README.md#not-present)\n")
        entry = load_catalog(root)[0]
        with self.assertRaisesRegex(CatalogError, "unresolved local fragments"):
            render_readme_html(root, entry, {entry.readme_path: entry}, set())

        self._write_fixture_readme(
            root,
            "recipes/community/target",
            {
                "title": "Target Example",
                "description": "Provides a second observable fixture result.",
            },
            body="## Present\n",
        )
        self._write_fixture_readme(
            root,
            "recipes/community/sample",
            body="[Missing](../target/README.md#not-present)\n",
        )
        entries = load_catalog(root)
        template = (ROOT / "site" / "templates" / "detail.html").read_text(
            encoding="utf-8"
        )
        pages, _ = render_detail_pages(root, entries, template)

        with self.assertRaisesRegex(CatalogError, "unresolved README fragment"):
            validate_detail_pages(root, entries, pages)


if __name__ == "__main__":
    unittest.main()
