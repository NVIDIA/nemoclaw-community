# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Narrow Slack compatibility patch for workspace-specific slash commands.

Hermes owns Slack rendering and interactive clarification. This recipe only
adds a catch-all reply for custom command names and sanitized delivery
diagnostics used by its guided verification flow.
"""
from __future__ import annotations

import logging
import re

from slack_diagnostic import (
    diagnostic_id,
    install_adapter_instrumentation,
    record_stage,
)


LOGGER = logging.getLogger("nemoclaw.slack_compat")


def _patch_runtime_slack_adapter(adapter_class: type) -> None:
    """Patch the namespaced Slack adapter returned by Hermes's registry."""
    diagnostic_installed = install_adapter_instrumentation(adapter_class)
    if adapter_class.__dict__.get("_nemoclaw_slack_compat_installed"):
        return

    original_connect = adapter_class.connect

    async def _patched_connect(self, *args, **kwargs):
        result = await original_connect(self, *args, **kwargs)
        if diagnostic_installed:
            record_stage(
                "",
                "socket_mode_connection",
                status="confirmed" if result else "failed",
                error_type="" if result else "ConnectFailure",
            )
        app = getattr(self, "_app", None)
        if app is not None and getattr(
            self, "_nemoclaw_unknown_command_app", None
        ) is not app:

            @app.command(re.compile(".+"))
            async def _handle_unknown_command(ack, command, respond):
                test_id = diagnostic_id(command.get("text", ""))
                if test_id and callable(
                    getattr(self, "_handle_slash_command", None)
                ):
                    await ack(
                        response_type="ephemeral",
                        text="Slack delivery diagnostic received.",
                    )
                    diagnostic_command = dict(command)
                    diagnostic_command["command"] = "/hermes"
                    await self._handle_slash_command(diagnostic_command)
                    return
                await ack()
                command_name = command.get("command", "this command")
                await respond(
                    f"I don't recognize `{command_name}`. "
                    "Send me a *direct message* or @mention me to chat"
                )

            self._nemoclaw_unknown_command_app = app
        return result

    adapter_class.connect = _patched_connect
    adapter_class._nemoclaw_slack_compat_installed = True


def _patch_slack_registry_factory() -> None:
    try:
        from gateway.platform_registry import PlatformRegistry

        original_create_adapter = PlatformRegistry.create_adapter
        if getattr(
            original_create_adapter,
            "_nemoclaw_slack_registry_compat",
            False,
        ):
            return

        def _create_adapter_with_slack_compat(self, name, config):
            adapter = original_create_adapter(self, name, config)
            if name == "slack" and adapter is not None:
                _patch_runtime_slack_adapter(type(adapter))
            return adapter

        _create_adapter_with_slack_compat._nemoclaw_slack_registry_compat = True
        PlatformRegistry.create_adapter = _create_adapter_with_slack_compat
    except Exception as exc:
        LOGGER.debug("Slack registry compatibility patch was not applied: %s", exc)


_patch_slack_registry_factory()
