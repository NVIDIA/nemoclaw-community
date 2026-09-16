# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase


EXAMPLE_DIR = Path(__file__).parents[2]
REFRESH_SCRIPT = EXAMPLE_DIR / "agents/hermes/refresh-placeholders.py"


class RefreshPlaceholdersTest(TestCase):
    def test_runtime_files_receive_exact_injected_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / ".env"
            config_file = root / "config.yaml"
            env_file.write_text(
                "SLACK_BOT_TOKEN=xoxb-OPENSHELL-RESOLVE-ENV-SLACK_BOT_TOKEN\n"
                "SLACK_APP_TOKEN=xapp-OPENSHELL-RESOLVE-ENV-SLACK_APP_TOKEN\n"
                "MS_GRAPH_ACCESS_TOKEN=openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN\n"
                "UNCHANGED=value\n",
                encoding="utf-8",
            )
            config_file.write_text(
                "platforms:\n"
                "  slack:\n"
                "    token: xoxb-OPENSHELL-RESOLVE-ENV-SLACK_BOT_TOKEN\n"
                "legacy_app_token: openshell:resolve:env:v16_SLACK_APP_TOKEN\n",
                encoding="utf-8",
            )

            injected = {
                "SLACK_BOT_TOKEN": (
                    "openshell:resolve:env:v17_SLACK_BOT_TOKEN"
                ),
                "SLACK_APP_TOKEN": (
                    "openshell:resolve:env:v17_SLACK_APP_TOKEN"
                ),
                "MS_GRAPH_ACCESS_TOKEN": (
                    "openshell:resolve:env:v17_MS_GRAPH_ACCESS_TOKEN"
                ),
            }
            process_env = {
                **os.environ,
                **injected,
                "NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS": " ".join(injected),
            }

            for _ in range(2):
                subprocess.run(
                    [
                        sys.executable,
                        str(REFRESH_SCRIPT),
                        str(env_file),
                        str(config_file),
                    ],
                    env=process_env,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            env_text = env_file.read_text(encoding="utf-8")
            config_text = config_file.read_text(encoding="utf-8")
            for key, placeholder in injected.items():
                self.assertIn(f"{key}={placeholder}\n", env_text)
            self.assertIn(injected["SLACK_BOT_TOKEN"], config_text)
            self.assertIn(injected["SLACK_APP_TOKEN"], config_text)
            self.assertNotIn("v16_SLACK_APP_TOKEN", config_text)
            self.assertIn("UNCHANGED=value\n", env_text)
            self.assertNotIn("xoxb-OPENSHELL", env_text + config_text)
            self.assertNotIn("xapp-OPENSHELL", env_text + config_text)

    def test_non_placeholder_values_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SLACK_BOT_TOKEN=placeholder-only\n", encoding="utf-8")
            process_env = {
                **os.environ,
                "SLACK_BOT_TOKEN": "not-a-placeholder",
                "NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS": "SLACK_BOT_TOKEN",
            }

            subprocess.run(
                [sys.executable, str(REFRESH_SCRIPT), str(env_file)],
                env=process_env,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                "SLACK_BOT_TOKEN=placeholder-only\n",
                env_file.read_text(encoding="utf-8"),
            )
