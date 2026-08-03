# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for the feature-detected Slack clarification shim."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
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

        async def connect(self, *args, **kwargs):
            self._app = FakeApp()
            return True

        def _get_client(self, chat_id):
            return self.client

        def _resolve_thread_ts(self, reply_to=None, metadata=None):
            return (metadata or {}).get("thread_id")

        def _is_interactive_user_authorized(self, user_id, **kwargs):
            return self.authorized and user_id == "U123"

    if native_clarify:
        async def native_send_clarify(self, **kwargs):
            return FakeSendResult(success=True, native=True, **kwargs)

        StubSlackAdapter.send_clarify = native_send_clarify

    return StubSlackAdapter


def load_patch(adapter_cls, module_name: str) -> None:
    plugins = ModuleType("plugins")
    platforms = ModuleType("plugins.platforms")
    slack = ModuleType("plugins.platforms.slack")
    adapter = ModuleType("plugins.platforms.slack.adapter")
    adapter.SlackAdapter = adapter_cls

    gateway = ModuleType("gateway")
    gateway_platforms = ModuleType("gateway.platforms")
    gateway_base = ModuleType("gateway.platforms.base")
    gateway_base.SendResult = FakeSendResult

    fake_modules = {
        "plugins": plugins,
        "plugins.platforms": platforms,
        "plugins.platforms.slack": slack,
        "plugins.platforms.slack.adapter": adapter,
        "gateway": gateway,
        "gateway.platforms": gateway_platforms,
        "gateway.platforms.base": gateway_base,
    }
    spec = importlib.util.spec_from_file_location(module_name, PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PATCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)


class SlackInteractiveCompatTest(unittest.TestCase):
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
