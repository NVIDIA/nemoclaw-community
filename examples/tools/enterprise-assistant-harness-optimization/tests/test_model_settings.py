# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harbor_agents.model_settings import (
    DEFAULT_BASE_URL,
    model_base_url,
    model_slug,
    profile_type,
    provider_name,
    write_provider_profile,
)


class ModelSettingsTest(unittest.TestCase):
    def test_environment_selects_any_model_slug_and_endpoint(self) -> None:
        with patch.dict(
            "os.environ",
            {"MODEL_SLUG": "my-nemotron", "MODEL_BASE_URL": "https://models.example.test/v1/"},
        ):
            self.assertEqual(model_slug(), "my-nemotron")
            self.assertEqual(model_base_url(), "https://models.example.test/v1")

    def test_custom_profile_binds_only_selected_host(self) -> None:
        url = "https://models.example.test/v1"
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "provider.yaml"
            name, kind = write_provider_profile(url, target)
            profile = target.read_text(encoding="utf-8")
            self.assertEqual(name, provider_name(url))
            self.assertEqual(kind, profile_type(url))
            self.assertIn(f"id: {kind}", profile)
            self.assertIn("host: models.example.test", profile)
            self.assertNotIn("host: integrate.api.nvidia.com", profile)
            self.assertIn("env_vars: [NVIDIA_API_KEY]", profile)

    def test_default_profile_keeps_existing_provider_identity(self) -> None:
        self.assertEqual(provider_name(DEFAULT_BASE_URL), "hermes-nvidia")
        self.assertEqual(profile_type(DEFAULT_BASE_URL), "hermes-nvidia-build")

    def test_rejects_insecure_or_ambiguous_base_urls(self) -> None:
        for url in (
            "http://models.example.test/v1",
            "https://user:secret@models.example.test/v1",
            "https://models.example.test/v1?key=secret",
            "https://models.example.test:bad/v1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                model_base_url(url)


if __name__ == "__main__":
    unittest.main()
