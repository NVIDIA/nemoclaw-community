# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for maintainer taxonomy validation and title conventions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_label_taxonomy import validate_taxonomy  # noqa: E402
from check_pr_title import is_valid_title  # noqa: E402
from audit_github_labels import build_audit  # noqa: E402


class GovernanceTaxonomyTests(unittest.TestCase):
    def test_taxonomy_is_consistent(self) -> None:
        self.assertEqual(validate_taxonomy(), [])

    def test_valid_titles(self) -> None:
        valid = (
            "feat(gitlab): add policy-scoped read access",
            "fix(outlook): reuse refresh-token cache",
            "docs: clarify setup",
            "chore(governance): adopt maintainer taxonomy",
        )
        for title in valid:
            with self.subTest(title=title):
                self.assertTrue(is_valid_title(title))

    def test_invalid_titles(self) -> None:
        invalid = (
            "Add policy-scoped read access",
            "feature(gitlab): add read access",
            "feat(GitLab): add read access",
            "feat: Add read access",
        )
        for title in invalid:
            with self.subTest(title=title):
                self.assertFalse(is_valid_title(title))

    def test_label_audit_is_read_only_diff(self) -> None:
        taxonomy = {
            "canonical_labels": [
                {
                    "name": "feature",
                    "description": "PR adds capability.",
                    "color": "a2eeef",
                }
            ],
            "label_families": {"area": {"entries": []}},
            "legacy_labels": ["enhancement"],
        }
        live = {
            "feature": {
                "name": "feature",
                "description": "Old description",
                "color": "a2eeef",
            },
            "enhancement": {
                "name": "enhancement",
                "description": "Legacy",
                "color": "a2eeef",
            },
        }
        audit = build_audit(taxonomy, live)
        self.assertEqual([entry["name"] for entry in audit["update"]], ["feature"])
        self.assertEqual(audit["legacy"], ["enhancement"])


if __name__ == "__main__":
    unittest.main()
