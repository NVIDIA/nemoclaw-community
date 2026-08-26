# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused positive and negative tests for the example catalog validator."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_catalog_parity import check_catalog_parity, parse_catalog

ROOT = Path(__file__).resolve().parents[2]


class CatalogParityTests(unittest.TestCase):
    def _fixture_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)

        shutil.copy2(ROOT / "README.md", root / "README.md")
        shutil.copy2(ROOT / "SUPPORT.md", root / "SUPPORT.md")
        shutil.copytree(ROOT / "site", root / "site")

        catalog_source = ROOT / "examples" / "README.md"
        catalog_target = root / "examples" / "README.md"
        catalog_target.parent.mkdir(parents=True)
        shutil.copy2(catalog_source, catalog_target)
        for entry in parse_catalog(catalog_source):
            target = root / entry.readme
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()

        return root

    def test_current_catalog_passes(self) -> None:
        self.assertEqual(check_catalog_parity(self._fixture_root()), [])

    def test_outcome_drift_is_rejected(self) -> None:
        root = self._fixture_root()
        first_entry = parse_catalog(root / "examples" / "README.md")[0]
        site_path = root / "site" / "index.html"
        site = site_path.read_text(encoding="utf-8")
        mutated, replacements = re.subn(
            r'(<p class="outcome">\s*).*?(\s*</p>)',
            lambda match: (
                f"{match.group(1)}Deliberately drifted outcome.{match.group(2)}"
            ),
            site,
            count=1,
            flags=re.DOTALL,
        )
        self.assertEqual(replacements, 1)
        site_path.write_text(mutated, encoding="utf-8")

        errors = check_catalog_parity(root)
        expected_error = (
            f"Outcome drift for {first_entry.name}.\n"
            "  site:    Deliberately drifted outcome.\n"
            f"  catalog: {first_entry.outcome}"
        )

        self.assertEqual(errors, [expected_error])


if __name__ == "__main__":
    unittest.main()
