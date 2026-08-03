# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Static integration checks for the NVTeam private-authority boundary."""

from __future__ import annotations

from pathlib import Path
import unittest


HERMES_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = Path(__file__).resolve().parents[3]
SKILL_DIR = HERMES_DIR / "skills" / "nemoclaw-nvteam"
REGISTRY_PATH = "/sandbox/.hermes/nvteam/persona-authorities.json"
VALIDATOR_PATH = "/usr/local/lib/nemoclaw/nvteam/validate-authorities.py"


class NVTeamRuntimeContractTest(unittest.TestCase):
    def test_registry_and_validator_stay_outside_agent_writable_state(self) -> None:
        dockerfile = (HERMES_DIR / "Dockerfile").read_text(encoding="utf-8")
        policy = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        authority_signals = (
            SKILL_DIR / "references" / "authority-signals.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "COPY agents/hermes/skills/nemoclaw-nvteam/"
            "scripts/validate_authorities.py",
            dockerfile,
        )
        self.assertIn(VALIDATOR_PATH, dockerfile)
        self.assertIn(
            f"chmod 555 {VALIDATOR_PATH}",
            dockerfile,
        )
        self.assertIn("mkdir -p /sandbox/.hermes/nvteam", dockerfile)
        self.assertIn("chmod 555 /sandbox/.hermes/nvteam", dockerfile)
        self.assertIn("  - /sandbox/.hermes\n", policy)

        for contract in (skill, authority_signals):
            self.assertIn(REGISTRY_PATH, contract)
            self.assertIn(VALIDATOR_PATH, contract)
            self.assertNotIn(
                "$HERMES_HOME/nvteam/persona-authorities.json",
                contract,
            )


if __name__ == "__main__":
    unittest.main()
