# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Focused contracts for the Community-owned Hermes configuration generator."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Optional, Tuple
import unittest

import yaml


HERMES_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = Path(__file__).resolve().parents[3]
GENERATOR = HERMES_DIR / "generate-config.ts"


class GenerateConfigTest(unittest.TestCase):
    def run_generator(
        self,
        *,
        channels: list[str],
        rich_blocks: Optional[str] = None,
        expect_success: bool = True,
    ) -> Tuple[subprocess.CompletedProcess, Optional[dict]]:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".hermes").mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "NEMOCLAW_MODEL": "test/model",
                    "NEMOCLAW_INFERENCE_BASE_URL": "https://inference.local/v1",
                    "NEMOCLAW_MESSAGING_CHANNELS_B64": base64.b64encode(
                        json.dumps(channels).encode("utf-8")
                    ).decode("ascii"),
                }
            )
            if rich_blocks is None:
                env.pop("NEMOCLAW_SLACK_RICH_BLOCKS", None)
            else:
                env["NEMOCLAW_SLACK_RICH_BLOCKS"] = rich_blocks

            result = subprocess.run(
                ["node", "--experimental-strip-types", str(GENERATOR)],
                check=False,
                capture_output=True,
                env=env,
                text=True,
            )
            if expect_success:
                self.assertEqual(result.returncode, 0, result.stderr)
                config = yaml.safe_load(
                    (home / ".hermes" / "config.yaml").read_text(encoding="utf-8")
                )
                return result, config

            self.assertNotEqual(result.returncode, 0)
            return result, None

    def test_default_is_schema_32_and_rich_blocks_on(self) -> None:
        _, config = self.run_generator(channels=["slack"])
        assert config is not None
        self.assertEqual(config["_config_version"], 32)
        self.assertIs(config["agent"]["verify_on_stop"], False)
        self.assertIs(config["platforms"]["slack"]["extra"]["rich_blocks"], True)
        self.assertIs(config["platforms"]["api_server"]["enabled"], True)

    def test_explicit_boolean_values_are_preserved(self) -> None:
        for raw, expected in (("false", False), ("true", True)):
            with self.subTest(raw=raw):
                _, config = self.run_generator(channels=["slack"], rich_blocks=raw)
                assert config is not None
                self.assertIs(
                    config["platforms"]["slack"]["extra"]["rich_blocks"],
                    expected,
                )

    def test_invalid_boolean_values_fail_closed(self) -> None:
        for raw in ("TRUE", "1", "yes", " true "):
            with self.subTest(raw=raw):
                result, _ = self.run_generator(
                    channels=["slack"],
                    rich_blocks=raw,
                    expect_success=False,
                )
                self.assertIn(
                    "NEMOCLAW_SLACK_RICH_BLOCKS must be either true or false",
                    result.stderr,
                )

    def test_setting_does_not_enable_slack(self) -> None:
        _, config = self.run_generator(channels=[], rich_blocks="true")
        assert config is not None
        self.assertNotIn("slack", config["platforms"])
        self.assertIs(config["platforms"]["api_server"]["enabled"], True)

    def test_build_setting_is_propagated_to_the_generator(self) -> None:
        dockerfile = (HERMES_DIR / "Dockerfile").read_text(encoding="utf-8")
        sandbox_script = (EXAMPLE_DIR / "scripts" / "03-sandbox.sh").read_text(
            encoding="utf-8"
        )
        env_example = (EXAMPLE_DIR / ".env.example").read_text(encoding="utf-8")

        self.assertEqual(dockerfile.count("ARG NEMOCLAW_SLACK_RICH_BLOCKS=true"), 1)
        self.assertIn(
            "NEMOCLAW_SLACK_RICH_BLOCKS=${NEMOCLAW_SLACK_RICH_BLOCKS}",
            dockerfile,
        )
        self.assertIn(
            '[NEMOCLAW_SLACK_RICH_BLOCKS]="$NEMOCLAW_SLACK_RICH_BLOCKS"',
            sandbox_script,
        )
        self.assertIn(
            'NEMOCLAW_SLACK_RICH_BLOCKS="${NEMOCLAW_SLACK_RICH_BLOCKS:-true}"',
            sandbox_script,
        )
        self.assertIn("NEMOCLAW_SLACK_RICH_BLOCKS=true", env_example)
        self.assertIn("verify-rich-block-renderer.py", dockerfile)

    def test_slack_interactive_clarification_contract_is_baked_in(self) -> None:
        dockerfile = (HERMES_DIR / "Dockerfile").read_text(encoding="utf-8")
        patch = (HERMES_DIR / "patches" / "sitecustomize.py").read_text(
            encoding="utf-8"
        )
        verifier = (
            HERMES_DIR / "tests" / "verify-rich-block-renderer.py"
        ).read_text(encoding="utf-8")

        self.assertIn("PYTHONPATH=/usr/local/lib/nemoclaw-patches", dockerfile)
        self.assertIn('"send_clarify" not in SlackAdapter.__dict__', patch)
        self.assertIn("nemoclaw_clarify_other", patch)
        self.assertIn("_is_interactive_user_authorized", patch)
        self.assertIn("resolve_gateway_clarify", patch)
        self.assertIn('"send_clarify" not in SlackAdapter.__dict__', verifier)


if __name__ == "__main__":
    unittest.main()
