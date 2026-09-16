# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest


HELPER = Path(__file__).parents[1] / "hermes-plugin" / "configure_dashboard_auth.py"


def load_helper():
    plugins = types.ModuleType("plugins")
    dashboard_auth = types.ModuleType("plugins.dashboard_auth")
    basic = types.ModuleType("plugins.dashboard_auth.basic")
    basic.hash_password = lambda password: f"hash:{len(password)}"
    yaml = types.ModuleType("yaml")
    yaml.safe_load = lambda text: {"model": "preserved"}
    yaml.safe_dump = lambda value, **_kwargs: repr(value)
    sys.modules["plugins"] = plugins
    sys.modules["plugins.dashboard_auth"] = dashboard_auth
    sys.modules["plugins.dashboard_auth.basic"] = basic
    sys.modules["yaml"] = yaml
    spec = importlib.util.spec_from_file_location("configure_dashboard_auth", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DashboardAuthHelperTests(unittest.TestCase):
    def test_writes_canonical_config_without_plaintext_password(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("model: preserved\n", encoding="utf-8")
            config_path.chmod(0o640)

            helper.write_basic_auth_config(
                config_path,
                username="admin",
                password_hash="scrypt-hash",
                signing_secret="signing-secret",
            )

            content = config_path.read_text(encoding="utf-8")
            self.assertIn("'model': 'preserved'", content)
            self.assertIn("'password_hash': 'scrypt-hash'", content)
            self.assertIn("'secret': 'signing-secret'", content)
            self.assertIn("'dashboard_auth/basic'", content)
            self.assertNotIn("plaintext-password", content)
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)

    def test_removes_all_legacy_dashboard_auth_env_entries(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "OTHER_SETTING=preserved\n"
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin\n"
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=old-plaintext\n"
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH=old-hash\n"
                "HERMES_DASHBOARD_BASIC_AUTH_SECRET=old-secret\n",
                encoding="utf-8",
            )
            env_path.chmod(0o640)

            helper.remove_legacy_env_entries(env_path)

            content = env_path.read_text(encoding="utf-8")
            self.assertEqual(content, "OTHER_SETTING=preserved\n")
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
