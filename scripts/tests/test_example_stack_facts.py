# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for README stack declarations and fixed-shape confirmation."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from example_stack_facts import (  # noqa: E402
    extract_example_stack_facts,
    parse_stack_declaration,
)


class ExampleStackFactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "sample"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def facts(
        self,
        nemoclaw: str,
        harness: str,
        openshell: str,
    ):
        declaration = parse_stack_declaration(nemoclaw, harness, openshell)
        return extract_example_stack_facts(self.root, declaration)

    def test_readme_stack_grammar_is_small_and_strict(self) -> None:
        valid = (
            ("v0.0.104", "OpenClaw 2026.7.1", "0.0.85"),
            ("N/A", "Hermes >=0.19.0", "Unknown"),
            ("Unpinned", "OpenClaw Unpinned", "Unpinned"),
            ("N/A", "N/A", "N/A"),
        )
        for values in valid:
            with self.subTest(values=values):
                parse_stack_declaration(*values)

        invalid = (
            ("latest", "OpenClaw 2026.7.1", "0.0.85"),
            ("v0.0.104", "Any agent", "0.0.85"),
            ("v0.0.104", "Hermes", "0.0.85"),
            ("v0.0.104", "Hermes 0.19.0", "current"),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                parse_stack_declaration(*values)

    def test_exact_nemoclaw_release_confirms_stock_stack(self) -> None:
        self.write(
            "Dockerfile",
            "ARG NEMOCLAW_VERSION=v0.0.104\n"
            "ARG NEMOCLAW_COMMIT=f389c9d872775006ae069473f58250fa8f3ad40f\n"
            "ARG NEMOCLAW_AGENT=openclaw\n"
            "ARG OPENSHELL_VERSION=0.0.85\n",
        )

        facts = self.facts("v0.0.104", "OpenClaw 2026.7.1", "0.0.85")

        self.assertEqual(facts.status, "confirmed")
        self.assertEqual(facts.nemoclaw.version, "v0.0.104")
        self.assertEqual(facts.harness.version, "2026.7.1")
        self.assertEqual(facts.openshell.version, "0.0.85")
        self.assertIn("inferred from NemoClaw", " ".join(facts.reasons))

    def test_nemoclaw_langchain_selector_uses_the_release_contract(self) -> None:
        self.write(
            "Dockerfile",
            "ARG NEMOCLAW_VERSION=v0.0.104\n"
            "ARG NEMOCLAW_AGENT=langchain-deepagents-code\n",
        )

        facts = self.facts(
            "v0.0.104", "LangChain Deep Agents Code 0.1.34", "0.0.85"
        )

        self.assertEqual(facts.status, "confirmed")
        self.assertEqual(facts.harness.name, "LangChain Deep Agents Code")

    def test_nemoclaw_release_allows_mixed_v_prefixes(self) -> None:
        self.write(
            "Dockerfile",
            "ARG NEMOCLAW_VERSION=0.0.104\n"
            "ARG NEMOCLAW_AGENT=openclaw\n",
        )

        facts = self.facts("v0.0.104", "OpenClaw 2026.7.1", "v0.0.85")

        self.assertEqual(facts.status, "confirmed")
        self.assertEqual(facts.nemoclaw.status, "confirmed")
        self.assertEqual(facts.openshell.status, "confirmed")

    def test_direct_component_allows_mixed_v_prefixes(self) -> None:
        self.write("Dockerfile", "ARG OPENSHELL_VERSION=v0.0.85\n")

        facts = self.facts("N/A", "N/A", "0.0.85")

        self.assertEqual(facts.status, "confirmed")
        self.assertEqual(facts.openshell.status, "confirmed")

    def test_direct_harness_can_mix_confirmed_and_readme_only_values(self) -> None:
        self.write(
            "agents/hermes/Dockerfile",
            "ARG HERMES_SEMVER=0.20.0\nFROM example/hermes:${HERMES_SEMVER}\n",
        )

        facts = self.facts("N/A", "Hermes 0.20.0", "0.0.85")

        self.assertEqual(facts.status, "unconfirmed")
        self.assertEqual(facts.harness.status, "confirmed")
        self.assertEqual(facts.openshell.status, "unconfirmed")

    def test_readme_only_exact_values_are_unconfirmed(self) -> None:
        facts = self.facts("v0.0.83", "Hermes 0.18.0", "0.0.72")

        self.assertEqual(facts.status, "unconfirmed")
        self.assertTrue(all(component.status == "unconfirmed" for component in (
            facts.nemoclaw,
            facts.harness,
            facts.openshell,
        )))

    def test_mutable_or_ranged_declarations_are_unpinned(self) -> None:
        facts = self.facts("Unpinned", "OpenClaw Unpinned", "Unpinned")

        self.assertEqual(facts.status, "unpinned")
        self.assertEqual(facts.nemoclaw.status, "unpinned")

    def test_unknown_declaration_remains_visible(self) -> None:
        facts = self.facts("Unpinned", "Unknown", "Unpinned")

        self.assertEqual(facts.status, "unknown")
        self.assertIsNone(facts.harness.name)
        self.assertIn("not established", " ".join(facts.reasons))

    def test_readme_and_code_disagreement_is_a_conflict(self) -> None:
        self.write("Dockerfile", "ARG OPENSHELL_VERSION=0.0.84\n")

        facts = self.facts("N/A", "N/A", "0.0.85")

        self.assertEqual(facts.status, "conflict")
        self.assertEqual(facts.openshell.status, "conflict")
        self.assertIn("conflicts", " ".join(facts.reasons))

    def test_nested_custom_layout_uses_readme_fallback(self) -> None:
        self.write(
            "helm/templates/startup-configmap.yaml",
            "NEMOCLAW_INSTALL_REF=v0.0.50\nOPENSHELL_VERSION=0.0.44\n",
        )

        facts = self.facts("v0.0.50", "OpenClaw 2026.5.18", "0.0.44")

        self.assertEqual(facts.status, "unconfirmed")
        self.assertEqual(facts.evidence_paths, ())

    def test_all_na_is_not_applicable(self) -> None:
        facts = self.facts("N/A", "N/A", "N/A")

        self.assertEqual(facts.status, "not-applicable")
        self.assertEqual(facts.harness.status, "not-applicable")

    def test_current_catalog_has_each_expected_verification_state(self) -> None:
        examples = ROOT / "examples"
        patterns = (
            "recipes/nvidia/*",
            "recipes/community/*",
            "recipes/partners/*/*",
            "demos/field/*",
            "tools/*",
        )
        roots = sorted(
            path
            for pattern in patterns
            for path in examples.glob(pattern)
            if path.is_dir() and (path / "README.md").is_file()
        )
        states: Counter[str] = Counter()
        for root in roots:
            rows = dict(
                re.findall(
                    r"^\| ([A-Za-z]+) \| ([^|]+) \|$",
                    (root / "README.md").read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
            )
            declaration = parse_stack_declaration(
                rows["NemoClaw"], rows["Harness"], rows["OpenShell"]
            )
            states[extract_example_stack_facts(root, declaration).status] += 1

        self.assertEqual(
            states,
            Counter(
                {
                    "unconfirmed": 7,
                    "unpinned": 11,
                    "unknown": 1,
                    "not-applicable": 1,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
