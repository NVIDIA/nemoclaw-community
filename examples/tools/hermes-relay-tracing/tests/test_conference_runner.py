# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]
RUNNER = REPOSITORY_ROOT / "scripts" / "run_conference_research_with_phoenix.sh"


class ConferenceRunnerTests(unittest.TestCase):
    def test_help_documents_default_and_comparison_profiles(self) -> None:
        result = subprocess.run(
            ["bash", str(RUNNER), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--model-profile PATH", result.stdout)
        self.assertIn("NVIDIA_API_KEY", result.stdout)
        self.assertIn("compatible model endpoint", result.stdout)

    def test_missing_model_profile_fails_before_running_tutorial(self) -> None:
        result = subprocess.run(
            ["bash", str(RUNNER), "--model-profile", "does-not-exist.env"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Model profile not found: does-not-exist.env", result.stderr)

    def test_unsupported_api_mode_fails_before_running_tutorial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.env"
            profile.write_text(
                "\n".join(
                    [
                        "MODEL_PROFILE_NAME=test",
                        "MODEL_PROFILE_MODEL=provider/model",
                        "MODEL_PROFILE_BASE_URL=https://provider.example.com/v1",
                        "MODEL_PROFILE_API_MODE=unsupported",
                        "MODEL_PROFILE_API_KEY_ENV=COMPARISON_API_KEY",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(RUNNER), "--model-profile", str(profile)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("MODEL_PROFILE_API_MODE must be", result.stderr)

    def test_unsafe_model_name_fails_before_running_tutorial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.env"
            profile.write_text(
                "\n".join(
                    [
                        "MODEL_PROFILE_NAME=test",
                        'MODEL_PROFILE_MODEL=provider/model"',
                        "MODEL_PROFILE_BASE_URL=https://provider.example.com/v1",
                        "MODEL_PROFILE_API_MODE=chat_completions",
                        "MODEL_PROFILE_API_KEY_ENV=COMPARISON_API_KEY",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(RUNNER), "--model-profile", str(profile)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "MODEL_PROFILE_MODEL contains unsupported characters", result.stderr
        )


if __name__ == "__main__":
    unittest.main()
