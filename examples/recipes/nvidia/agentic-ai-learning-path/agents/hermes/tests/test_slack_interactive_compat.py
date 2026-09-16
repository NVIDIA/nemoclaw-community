# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Behavior test for the recipe-specific Slack slash-command fallback."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
import unittest
from unittest import mock


PATCH_PATH = Path(__file__).resolve().parents[1] / "patches" / "sitecustomize.py"


class FakeApp:
    def __init__(self) -> None:
        self.commands = []

    def command(self, matcher):
        def decorator(callback):
            self.commands.append((matcher, callback))
            return callback

        return decorator


class FakeSlackAdapter:
    async def connect(self):
        self._app = FakeApp()
        return True


class FakePlatformRegistry:
    def create_adapter(self, name, _config):
        return FakeSlackAdapter() if name == "slack" else None


class SlackSlashCommandCompatTest(unittest.TestCase):
    def test_runtime_adapter_registers_unknown_command_reply(self) -> None:
        gateway = ModuleType("gateway")
        registry_module = ModuleType("gateway.platform_registry")
        registry_module.PlatformRegistry = FakePlatformRegistry

        spec = importlib.util.spec_from_file_location(
            "_learning_path_sitecustomize_test",
            PATCH_PATH,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(
            sys.modules,
            {
                "gateway": gateway,
                "gateway.platform_registry": registry_module,
            },
        ):
            spec.loader.exec_module(module)

        adapter = FakePlatformRegistry().create_adapter("slack", None)
        assert adapter is not None
        asyncio.run(adapter.connect())

        self.assertEqual(len(adapter._app.commands), 1)
        matcher, callback = adapter._app.commands[0]
        self.assertIsInstance(matcher, re.Pattern)
        self.assertTrue(matcher.fullmatch("/workspace-command"))

        acknowledgements = []
        responses = []

        async def ack():
            acknowledgements.append(True)

        async def respond(message):
            responses.append(message)

        asyncio.run(
            callback(
                ack,
                {"command": "/workspace-command"},
                respond,
            )
        )

        self.assertEqual(acknowledgements, [True])
        self.assertEqual(len(responses), 1)
        self.assertIn("/workspace-command", responses[0])


if __name__ == "__main__":
    unittest.main()
