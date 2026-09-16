# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).parents[1]
AUTH_HELPER = ROOT / "hermes-plugin" / "configure_dashboard_auth.py"
PUBLIC_URL_HELPER = ROOT / "hermes-plugin" / "configure_dashboard_public_url.py"


def load_helper():
    yaml = types.ModuleType("yaml")
    yaml.safe_load = lambda _text: {"model": "preserved"}
    yaml.safe_dump = lambda value, **_kwargs: repr(value)
    sys.modules["yaml"] = yaml

    auth_spec = importlib.util.spec_from_file_location(
        "configure_dashboard_auth", AUTH_HELPER
    )
    auth = importlib.util.module_from_spec(auth_spec)
    auth.hash_password = lambda password: f"hash:{len(password)}"
    assert auth_spec.loader is not None

    plugins = types.ModuleType("plugins")
    dashboard_auth = types.ModuleType("plugins.dashboard_auth")
    basic = types.ModuleType("plugins.dashboard_auth.basic")
    basic.hash_password = auth.hash_password
    sys.modules["plugins"] = plugins
    sys.modules["plugins.dashboard_auth"] = dashboard_auth
    sys.modules["plugins.dashboard_auth.basic"] = basic
    auth_spec.loader.exec_module(auth)
    sys.modules["configure_dashboard_auth"] = auth

    public_spec = importlib.util.spec_from_file_location(
        "configure_dashboard_public_url", PUBLIC_URL_HELPER
    )
    public = importlib.util.module_from_spec(public_spec)
    assert public_spec.loader is not None
    public_spec.loader.exec_module(public)
    return public


class DashboardPublicUrlHelperTests(unittest.TestCase):
    def test_accepts_https_origin_and_removes_trailing_slash(self):
        helper = load_helper()
        self.assertEqual(
            helper.validated_origin("https://18889-example.gobrev.dev/"),
            "https://18889-example.gobrev.dev",
        )

    def test_rejects_path_query_credentials_and_http(self):
        helper = load_helper()
        invalid_values = (
            "http://example.test",
            "https://example.test/path",
            "https://example.test?query=1",
            "https://user:password@example.test",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(SystemExit):
                helper.validated_origin(value)

    def test_writes_isolated_dashboard_profile(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("model: preserved\n", encoding="utf-8")
            helper.dashboard_config_path = lambda: config_path

            helper.set_public_url("https://18889-example.gobrev.dev/")

            content = config_path.read_text(encoding="utf-8")
            self.assertIn("'model': 'preserved'", content)
            self.assertIn(
                "'public_url': 'https://18889-example.gobrev.dev'", content
            )
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
