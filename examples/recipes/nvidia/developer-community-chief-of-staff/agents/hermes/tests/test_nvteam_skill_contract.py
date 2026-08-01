# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the reusable NemoClaw Community NVTeam skill."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


HERMES_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = Path(__file__).resolve().parents[3]
SKILL_DIR = HERMES_DIR / "skills" / "nemoclaw-nvteam"

PERSONAS = {
    "river": "Product Manager",
    "quinn": "Technical Program Manager",
    "akira": "Backend and Systems Engineer",
    "jordan": "Data and ML Engineer",
    "robin": "Quality Engineer",
    "alex": "Platform and SRE",
    "morgan": "Security Engineer",
    "parker": "Technical Marketing Engineer",
}


class NVTeamSkillContractTest(unittest.TestCase):
    def test_skill_has_eight_role_aware_personas(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        soul = (HERMES_DIR / "SOUL.md").read_text(encoding="utf-8")
        normalized_soul = " ".join(soul.split())
        response_profile = (
            SKILL_DIR / "references" / "response-profiles.md"
        ).read_text(encoding="utf-8")

        self.assertIn("name: nemoclaw-nvteam", skill)
        self.assertIn("Introduce the Team Once", skill)
        self.assertIn("<Name> (<Role>) active", skill)
        self.assertIn("## Your Community NVTeam", response_profile)
        for name, role in PERSONAS.items():
            self.assertTrue(
                (SKILL_DIR / "references" / "personas" / f"{name}.md").is_file()
            )
            display_name = name.capitalize()
            self.assertIn(display_name, normalized_soul)
            self.assertIn(role, normalized_soul)
            self.assertIn(display_name, response_profile)

    def test_product_attribution_boundary_is_visible_at_every_entry_point(
        self,
    ) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        soul = (HERMES_DIR / "SOUL.md").read_text(encoding="utf-8")
        readme = (EXAMPLE_DIR / "README.md").read_text(encoding="utf-8")
        openai_yaml = (SKILL_DIR / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("## Keep Product Attribution Explicit", skill)
        for content in (skill, soul, readme):
            normalized = " ".join(content.split()).lower()
            self.assertIn("community recipe", normalized)
            self.assertIn("core nemoclaw", normalized)
            self.assertIn("not a built-in", normalized)
        self.assertIn('display_name: "NemoClaw Community NVTeam"', openai_yaml)
        self.assertIn("Community recipe's local role lenses", openai_yaml)

    def test_shared_writing_and_principles_are_not_duplicated(self) -> None:
        references = SKILL_DIR / "references"
        self.assertTrue((references / "technical-writing.md").is_file())
        self.assertTrue((references / "nvidia-working-principles.md").is_file())

        for persona in ("akira", "jordan", "robin", "alex", "morgan", "parker"):
            card = (references / "personas" / f"{persona}.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("technical-writing.md", card)
            self.assertNotIn("Aim for 20 words", card)

        principles = (references / "nvidia-working-principles.md").read_text(
            encoding="utf-8"
        )
        for term in (
            "Mission is the Boss",
            "SOL: Speed of Light",
            "LUA: Listen, Understand, Answer",
            "As Much as Needed, As Little as Possible",
            "Intellectual Honesty",
            "One Team",
            "First Principles",
            "Excellence and Determination",
        ):
            self.assertIn(term, principles)

    def test_parker_knows_recipe_community_workflows(self) -> None:
        parker = (
            SKILL_DIR / "references" / "personas" / "parker.md"
        ).read_text(encoding="utf-8")
        for skill_name in (
            "github-readonly-live",
            "slack-channel-finder",
            "slack-channel-summarizer",
            "outlook-email-search",
            "source-etl-query",
            "cross-source-gap-analysis",
        ):
            self.assertIn(skill_name, parker)
        self.assertNotIn("nemoclaw-autoheal`:", parker)

    def test_evals_cover_routing_delegation_rich_blocks_and_authority(self) -> None:
        evals = json.loads(
            (SKILL_DIR / "evals" / "evals.json").read_text(encoding="utf-8")
        )
        ids = {case["id"] for case in evals}
        for persona in PERSONAS:
            self.assertTrue(
                any(case_id.startswith(f"nvteam-routing-{persona}") for case_id in ids),
                persona,
            )
        for required in (
            "nvteam-session-intro-slack-001",
            "nvteam-delegation-positive-001",
            "nvteam-delegation-negative-001",
            "nvteam-interactive-clarify-001",
            "nvteam-parker-community-workflow-001",
            "nvteam-principles-sol-001",
            "nvteam-principles-lua-001",
            "nvteam-authority-jordan-001",
            "nvteam-negative-core-product-attribution-001",
            "nvteam-explicit-product-comparison-001",
        ):
            self.assertIn(required, ids)
        self.assertTrue(
            all(
                case.get("expected_skill") in {None, "nemoclaw-nvteam"}
                for case in evals
            )
        )

    def test_recipe_has_no_legacy_skill_name(self) -> None:
        legacy = "nemoclaw-enterprise-" + "nvteam"
        matches = []
        for path in EXAMPLE_DIR.rglob("*"):
            if path.is_file() and path.suffix in {
                ".md",
                ".json",
                ".yaml",
                ".py",
                ".sh",
                ".ts",
            }:
                if legacy in path.read_text(encoding="utf-8", errors="ignore"):
                    matches.append(str(path.relative_to(EXAMPLE_DIR)))
        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
