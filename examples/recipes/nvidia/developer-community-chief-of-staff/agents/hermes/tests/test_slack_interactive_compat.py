# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for the feature-detected Slack clarification shim."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


PATCH_PATH = Path(__file__).resolve().parents[1] / "patches" / "sitecustomize.py"


class FakeSendResult:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeClient:
    def __init__(self) -> None:
        self.posts = []
        self.updates = []

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ts": "171.001"}

    async def chat_update(self, **kwargs):
        self.updates.append(kwargs)
        return {"ok": True}


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


def make_adapter(*, native_clarify: bool = False):
    class BaseAdapter:
        async def send_clarify(self, **kwargs):
            return FakeSendResult(success=True, fallback=True, **kwargs)

    class StubSlackAdapter(BaseAdapter):
        def __init__(self) -> None:
            self._app = None
            self.client = FakeClient()
            self.config = SimpleNamespace(extra={})
            self.authorized = True
            self.slash_commands = []

        async def connect(self, *args, **kwargs):
            self._app = FakeApp()
            return True

        def _get_client(self, chat_id):
            return self.client

        def _resolve_thread_ts(self, reply_to=None, metadata=None):
            return (metadata or {}).get("thread_id")

        def _is_interactive_user_authorized(self, user_id, **kwargs):
            return self.authorized and user_id == "U123"

        async def _handle_slash_command(self, command):
            self.slash_commands.append(command)

    if native_clarify:
        async def native_send_clarify(self, **kwargs):
            return FakeSendResult(success=True, native=True, **kwargs)

        StubSlackAdapter.send_clarify = native_send_clarify

    return StubSlackAdapter


def load_patch(adapter_cls, module_name: str):
    plugins = ModuleType("plugins")
    platforms = ModuleType("plugins.platforms")
    slack = ModuleType("plugins.platforms.slack")
    adapter = ModuleType("plugins.platforms.slack.adapter")
    adapter.SlackAdapter = adapter_cls

    gateway = ModuleType("gateway")
    gateway_platforms = ModuleType("gateway.platforms")
    gateway_base = ModuleType("gateway.platforms.base")
    gateway_base.SendResult = FakeSendResult
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
        "plugins": plugins,
        "plugins.platforms": platforms,
        "plugins.platforms.slack": slack,
        "plugins.platforms.slack.adapter": adapter,
        "gateway": gateway,
        "gateway.platforms": gateway_platforms,
        "gateway.platforms.base": gateway_base,
        "gateway.platform_registry": gateway_registry,
    }
    spec = importlib.util.spec_from_file_location(module_name, PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PATCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)
    return SimpleNamespace(
        module=module,
        platform_registry_cls=FakePlatformRegistry,
    )


class SlackInteractiveCompatTest(unittest.TestCase):
    def test_adds_hermes_root_before_importing_the_adapter(self) -> None:
        adapter_cls = make_adapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "plugins").mkdir()
            clean_path = [entry for entry in sys.path if entry != temp_dir]
            with (
                mock.patch.dict(
                    os.environ,
                    {"NEMOCLAW_HERMES_ROOT": temp_dir},
                ),
                mock.patch.object(sys, "path", clean_path),
            ):
                load_patch(adapter_cls, "_nvteam_sitecustomize_path_test")
                self.assertEqual(temp_dir, sys.path[0])

    def test_patches_the_namespaced_runtime_adapter_from_the_registry(self) -> None:
        template_cls = make_adapter()
        loaded = load_patch(
            template_cls,
            "_nvteam_sitecustomize_registry_test",
        )
        runtime_cls = make_adapter()
        registry = loaded.platform_registry_cls(runtime_cls)

        adapter = registry.create_adapter("slack", None)
        asyncio.run(adapter.connect())
        result = asyncio.run(
            adapter.send_clarify(
                chat_id="D123",
                question="Which V0?",
                choices=["Recovery", "First success"],
                clarify_id="clarify-registry",
                session_key="session-1",
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(
            loaded.module.__name__,
            runtime_cls.__dict__["send_clarify"].__module__,
        )
        self.assertEqual(
            ["section", "actions"],
            [block["type"] for block in adapter.client.posts[-1]["blocks"]],
        )

    def test_custom_slash_diagnostic_enters_the_hermes_message_path(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_diagnostic_slash_test")
        adapter = adapter_cls()
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
            [{"response_type": "ephemeral", "text": "Slack delivery diagnostic received."}],
        )
        self.assertEqual(adapter.slash_commands[0]["command"], "/hermes")
        self.assertEqual(responses, [])

    def test_other_custom_slash_commands_keep_the_help_response(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_unknown_slash_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())
        callback = adapter._app.commands[-1][1]
        responses = []

        async def ack(**kwargs):
            self.assertEqual(kwargs, {})

        async def respond(message):
            responses.append(message)

        asyncio.run(
            callback(
                ack,
                {"command": "/alice-nemoclaw", "text": "ordinary request"},
                respond,
            )
        )

        self.assertEqual(adapter.slash_commands, [])
        self.assertIn("don't recognize", responses[0])

    def test_adds_buttons_and_resolves_an_authorized_choice(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_choice_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())

        result = asyncio.run(
            adapter.send_clarify(
                chat_id="D123",
                question="Which V0?",
                choices=["Recovery", "First success", "Abandonment"],
                clarify_id="clarify-1",
                session_key="session-1",
                metadata={"thread_id": "170.000"},
            )
        )

        self.assertTrue(result.success)
        self.assertFalse(hasattr(result, "fallback"))
        payload = adapter.client.posts[-1]
        self.assertEqual("170.000", payload["thread_ts"])
        actions = payload["blocks"][1]["elements"]
        self.assertEqual(4, len(actions))
        self.assertEqual("nemoclaw_clarify_choice_0", actions[0]["action_id"])
        self.assertEqual("nemoclaw_clarify_other", actions[-1]["action_id"])

        resolved = []

        class Entry:
            choices = ["Recovery", "First success", "Abandonment"]

        clarify_gateway = SimpleNamespace(
            _entries={"clarify-1": Entry()},
            mark_awaiting_text=lambda clarify_id: True,
            resolve_gateway_clarify=lambda clarify_id, choice: (
                resolved.append((clarify_id, choice)) or True
            ),
        )
        tools_module = ModuleType("tools")
        tools_module.clarify_gateway = clarify_gateway

        acked = []

        async def ack():
            acked.append(True)

        body = {
            "message": {
                "ts": "171.001",
                "blocks": payload["blocks"],
            },
            "channel": {"id": "D123"},
            "user": {"id": "U123", "name": "Ada"},
        }
        action = {
            "action_id": "nemoclaw_clarify_choice_1",
            "value": "clarify-1|1",
        }
        with mock.patch.dict(sys.modules, {"tools": tools_module}):
            asyncio.run(
                adapter._nemoclaw_handle_clarify_action(ack, body, action)
            )

        self.assertEqual([True], acked)
        self.assertEqual([("clarify-1", "First success")], resolved)
        update = adapter.client.updates[-1]
        self.assertIn("Ada: First success", update["text"])
        self.assertTrue(all(block["type"] != "actions" for block in update["blocks"]))

    def test_other_waits_for_a_typed_answer(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_other_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())
        result = asyncio.run(
            adapter.send_clarify(
                chat_id="D123",
                question="Which V0?",
                choices=["Recovery", "First success"],
                clarify_id="clarify-other",
                session_key="session-1",
            )
        )

        waiting = []
        clarify_gateway = SimpleNamespace(
            mark_awaiting_text=lambda clarify_id: (
                waiting.append(clarify_id) or True
            ),
        )
        tools_module = ModuleType("tools")
        tools_module.clarify_gateway = clarify_gateway

        async def ack():
            return None

        body = {
            "message": {
                "ts": result.message_id,
                "blocks": adapter.client.posts[-1]["blocks"],
            },
            "channel": {"id": "D123"},
            "user": {"id": "U123", "name": "Ada"},
        }
        action = {
            "action_id": "nemoclaw_clarify_other",
            "value": "clarify-other|other",
        }
        with mock.patch.dict(sys.modules, {"tools": tools_module}):
            asyncio.run(adapter._nemoclaw_handle_clarify_action(ack, body, action))

        self.assertEqual(["clarify-other"], waiting)
        self.assertIn("Awaiting typed answer", adapter.client.updates[-1]["text"])

    def test_expired_and_repeated_clicks_do_not_resolve_twice(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_repeat_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())
        result = asyncio.run(
            adapter.send_clarify(
                chat_id="D123",
                question="Which V0?",
                choices=["Recovery"],
                clarify_id="clarify-repeat",
                session_key="session-1",
            )
        )

        resolved = []

        class Entry:
            choices = ["Recovery"]

        clarify_gateway = SimpleNamespace(
            _entries={"clarify-repeat": Entry()},
            resolve_gateway_clarify=lambda clarify_id, choice: (
                resolved.append((clarify_id, choice)) or True
            ),
        )
        tools_module = ModuleType("tools")
        tools_module.clarify_gateway = clarify_gateway

        async def ack():
            return None

        body = {
            "message": {
                "ts": result.message_id,
                "blocks": adapter.client.posts[-1]["blocks"],
            },
            "channel": {"id": "D123"},
            "user": {"id": "U123", "name": "Ada"},
        }
        action = {
            "action_id": "nemoclaw_clarify_choice_0",
            "value": "clarify-repeat|0",
        }
        with mock.patch.dict(sys.modules, {"tools": tools_module}):
            asyncio.run(adapter._nemoclaw_handle_clarify_action(ack, body, action))
            asyncio.run(adapter._nemoclaw_handle_clarify_action(ack, body, action))

        self.assertEqual([("clarify-repeat", "Recovery")], resolved)
        self.assertEqual(1, len(adapter.client.updates))

        expired_result = asyncio.run(
            adapter.send_clarify(
                chat_id="D123",
                question="Which V0 now?",
                choices=["Recovery"],
                clarify_id="clarify-expired",
                session_key="session-1",
            )
        )
        expired_body = {
            **body,
            "message": {
                "ts": expired_result.message_id,
                "blocks": adapter.client.posts[-1]["blocks"],
            },
        }
        expired_action = {
            "action_id": "nemoclaw_clarify_choice_0",
            "value": "clarify-expired|0",
        }
        clarify_gateway._entries = {}
        with mock.patch.dict(sys.modules, {"tools": tools_module}):
            asyncio.run(
                adapter._nemoclaw_handle_clarify_action(
                    ack, expired_body, expired_action
                )
            )
        self.assertIn("expired", adapter.client.updates[-1]["text"])

    def test_open_ended_and_over_limit_prompts_use_text_fallback(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_fallback_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())

        for choices in ([], ["One", "Two", "Three", "Four", "Five"]):
            result = asyncio.run(
                adapter.send_clarify(
                    chat_id="D123",
                    question="Choose",
                    choices=choices,
                    clarify_id="clarify-fallback",
                    session_key="session-1",
                )
            )
            self.assertTrue(result.fallback)

        self.assertEqual([], adapter.client.posts)

    def test_rejects_an_unauthorized_click(self) -> None:
        adapter_cls = make_adapter()
        load_patch(adapter_cls, "_nvteam_sitecustomize_auth_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())
        adapter._nemoclaw_clarify_resolved = {"171.001": False}
        adapter.authorized = False

        async def ack():
            return None

        body = {
            "message": {"ts": "171.001", "blocks": []},
            "channel": {"id": "D123"},
            "user": {"id": "U123", "name": "Ada"},
        }
        action = {
            "action_id": "nemoclaw_clarify_choice_0",
            "value": "clarify-1|0",
        }
        with self.assertLogs("nemoclaw.slack_compat", level="WARNING"):
            asyncio.run(adapter._nemoclaw_handle_clarify_action(ack, body, action))

        self.assertEqual({"171.001": False}, adapter._nemoclaw_clarify_resolved)
        self.assertEqual([], adapter.client.updates)

    def test_stands_down_for_native_slack_clarification(self) -> None:
        adapter_cls = make_adapter(native_clarify=True)
        native_method = adapter_cls.__dict__["send_clarify"]
        load_patch(adapter_cls, "_nvteam_sitecustomize_native_test")
        adapter = adapter_cls()
        asyncio.run(adapter.connect())

        self.assertIs(native_method, adapter_cls.__dict__["send_clarify"])
        self.assertFalse(hasattr(adapter_cls, "_nemoclaw_handle_clarify_action"))
        self.assertFalse(
            any(
                matcher == "nemoclaw_clarify_other"
                for matcher, _callback in adapter._app.actions
            )
        )


if __name__ == "__main__":
    unittest.main()
