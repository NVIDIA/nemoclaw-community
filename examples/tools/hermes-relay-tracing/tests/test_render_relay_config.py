# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))

import render_relay_config


class RenderRelayConfigTests(unittest.TestCase):
    def test_smoke_contract_defines_task_prompt_and_expected_output(self) -> None:
        values: dict[str, str] = {}
        for line in (REPOSITORY_ROOT / "config" / "smoke.env").read_text(
            encoding="utf-8"
        ).splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", maxsplit=1)
            values[key] = value.strip().strip("'\"")

        self.assertTrue(values["SMOKE_QUERY"])
        self.assertTrue(values["SMOKE_EXPECTED_OUTPUT"])
        self.assertTrue(values["SMOKE_REQUIRED_TOOL_COMMAND"])
        self.assertEqual(values["HERMES_REF"], "v2026.9.7")
        self.assertEqual(
            values["HERMES_COMMIT"], "2237be355906fbe6065ce1815711eee52b2d646e"
        )
        self.assertEqual(values["HERMES_VERSION"], "0.21.1")
        self.assertEqual(values["NEMO_RELAY_VERSION"], "0.8.3")
        self.assertEqual(values["UV_VERSION"], "0.12.9")
        self.assertEqual(
            values["UV_INSTALLER_SHA256"],
            "222e006c0fe4a0d793031833e469b21df72311f4e3526ffecca0e19e6dfabc32",
        )
        self.assertEqual(
            values["SMOKE_MODEL"], "nvidia/nemotron-3.5-lightning-30b-a3b"
        )
        self.assertEqual(
            values["NVIDIA_BASE_URL"], "https://integrate.api.nvidia.com/v1"
        )
        self.assertEqual(values["NVIDIA_API_MODE"], "chat_completions")
        self.assertEqual(values["SMOKE_TERMINAL_CWD"], "/root")
        self.assertIn(
            "/opt/nemo-relay-hermes-tutorial/sample.py", values["SMOKE_QUERY"]
        )
        dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("WORKDIR /opt/nemo-relay-hermes-tutorial", dockerfile)
        self.assertIn("COPY sample-project/sample.py ./sample.py", dockerfile)

    def test_comparison_profile_example_defines_required_fields(self) -> None:
        values: dict[str, str] = {}
        for line in (
            REPOSITORY_ROOT / "config" / "model_profile.env.example"
        ).read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", maxsplit=1)
            values[key] = value.strip().strip("'\"")

        self.assertEqual(values["MODEL_PROFILE_NAME"], "comparison")
        self.assertEqual(values["MODEL_PROFILE_API_MODE"], "chat_completions")
        self.assertEqual(values["MODEL_PROFILE_API_KEY_ENV"], "COMPARISON_API_KEY")

    def test_render_config_uses_absolute_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = render_relay_config.render_config(
                Path(directory) / "trace output", "nvidia/test-model"
            )

        self.assertIn('model_name = "nvidia/test-model"', config)
        self.assertIn('filename = "run.jsonl"', config)
        self.assertNotIn("[components.config.opentelemetry]", config)
        self.assertNotIn("__RELAY_OUTPUT_ROOT__", config)

    def test_render_config_can_add_a_phoenix_openinference_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = render_relay_config.render_config(
                Path(directory),
                "nvidia/test-model",
                openinference_endpoint="http://127.0.0.1:6006/v1/traces",
                openinference_project="tutorial-run",
            )

        self.assertIn("[components.config.opentelemetry]", config)
        self.assertIn('type = "openinference"', config)
        self.assertIn('endpoint = "http://127.0.0.1:6006/v1/traces"', config)
        self.assertIn("timeout_millis = 30000", config)
        self.assertIn("scheduled_delay_millis = 600000", config)
        self.assertIn('"openinference.project.name" = "tutorial-run"', config)

    def test_render_config_requires_complete_openinference_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "openinference_project"):
                render_relay_config.render_config(
                    Path(directory),
                    "nvidia/test-model",
                    openinference_endpoint="http://127.0.0.1:6006/v1/traces",
                )

    def test_main_rejects_empty_model_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                render_relay_config.main(
                    [
                        "--output",
                        str(Path(directory) / "plugins.toml"),
                        "--output-directory",
                        directory,
                        "--model-name",
                        "   ",
                    ]
                )
