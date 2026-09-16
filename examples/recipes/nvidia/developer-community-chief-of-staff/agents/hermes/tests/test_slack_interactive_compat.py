# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for the narrow Slack command compatibility patch."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


PATCH_PATH = Path(__file__).resolve().parents[1] / "patches" / "sitecustomize.py"


class FakeApp:
    def __init__(self) -> None:
        self.commands = []
        self.actions = []

    def command(self, matcher):
        def decorator(callback):
            self.commands.append((matcher, callback))
            return callback

        return decorator

    def action(self, matcher):
        def decorator(callback):
            self.actions.append((matcher, callback))
            return callback

        return decorator


def make_adapter():
    class StubSlackAdapter:
        def __init__(self) -> None:
            self._app = None
            self.slash_commands = []

        async def connect(self, *args, **kwargs):
            self._app = FakeApp()
            return True

        async def send_clarify(self, **kwargs):
            return SimpleNamespace(success=True, native=True, values=kwargs)

        async def _handle_slash_command(self, command):
            self.slash_commands.append(command)

    return StubSlackAdapter


def load_patch(module_name: str):
    gateway = ModuleType("gateway")
    gateway_registry = ModuleType("gateway.platform_registry")

    class FakePlatformRegistry:
        def __init__(self, runtime_adapter_cls=None) -> None:
            self.runtime_adapter_cls = runtime_adapter_cls

        def create_adapter(self, name, config):
            if name != "slack" or self.runtime_adapter_cls is None:
                return None
            return self.runtime_adapter_cls()

    gateway_registry.PlatformRegistry = FakePlatformRegistry
    fake_modules = {
        "gateway": gateway,
        "gateway.platform_registry": gateway_registry,
    }
    spec = importlib.util.spec_from_file_location(module_name, PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PATCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    with (
        mock.patch.object(
            sys,
            "path",
            [str(PATCH_PATH.parent), *sys.path],
        ),
        mock.patch.dict(sys.modules, fake_modules),
    ):
        spec.loader.exec_module(module)
    return SimpleNamespace(
        module=module,
        platform_registry_cls=FakePlatformRegistry,
    )


def create_adapter(adapter_cls, module_name: str):
    loaded = load_patch(module_name)
    registry = loaded.platform_registry_cls(adapter_cls)
    return loaded, registry.create_adapter("slack", None)


class SlackCommandCompatTest(unittest.TestCase):
    def test_patches_runtime_connect_and_preserves_native_clarification(self) -> None:
        adapter_cls = make_adapter()
        native_method = adapter_cls.__dict__["send_clarify"]
        loaded, adapter = create_adapter(
            adapter_cls,
            "_nemoclaw_sitecustomize_native_test",
        )
        asyncio.run(adapter.connect())

        result = asyncio.run(adapter.send_clarify(question="Which V0?"))
        self.assertTrue(result.native)
        self.assertIs(native_method, adapter_cls.__dict__["send_clarify"])
        self.assertEqual(
            loaded.module.__name__,
            adapter_cls.__dict__["connect"].__module__,
        )
        self.assertEqual([], adapter._app.actions)

    def test_custom_slash_diagnostic_enters_the_hermes_message_path(self) -> None:
        adapter_cls = make_adapter()
        _, adapter = create_adapter(
            adapter_cls,
            "_nemoclaw_sitecustomize_diagnostic_test",
        )
        asyncio.run(adapter.connect())
        callback = adapter._app.commands[-1][1]
        acknowledgements = []
        responses = []

        async def ack(**kwargs):
            acknowledgements.append(kwargs)

        async def respond(message):
            responses.append(message)

        asyncio.run(
            callback(
                ack,
                {
                    "command": "/alice-nemoclaw",
                    "text": "NemoClaw delivery diagnostic NC-1234ABCD",
                },
                respond,
            )
        )

        self.assertEqual(
            acknowledgements,
            [
                {
                    "response_type": "ephemeral",
                    "text": "Slack delivery diagnostic received.",
                }
            ],
        )
        self.assertEqual("/hermes", adapter.slash_commands[0]["command"])
        self.assertEqual([], responses)

    def test_other_custom_slash_commands_keep_the_help_response(self) -> None:
        adapter_cls = make_adapter()
        _, adapter = create_adapter(
            adapter_cls,
            "_nemoclaw_sitecustomize_unknown_test",
        )
        asyncio.run(adapter.connect())
        callback = adapter._app.commands[-1][1]
        responses = []

        async def ack(**kwargs):
            self.assertEqual({}, kwargs)

        async def respond(message):
            responses.append(message)

        asyncio.run(
            callback(
                ack,
                {"command": "/alice-nemoclaw", "text": "ordinary request"},
                respond,
            )
        )

        self.assertEqual([], adapter.slash_commands)
        self.assertIn("don't recognize", responses[0])


if __name__ == "__main__":
    unittest.main()
