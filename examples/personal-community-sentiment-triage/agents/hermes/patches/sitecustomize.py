# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Patch Hermes's Slack adapter with a catch-all slash-command handler.

Hermes registers only `/hermes` as its bolt command. Workspace-specific names
(e.g. `/my-assistant`) produce an `Unhandled request` warning and no user
feedback. This module patches `SlackAdapter.connect` so any other slash
command gets a friendly "I don't recognize this" reply.

Auto-loaded by Python's site initialization — the Dockerfile symlinks this
file into the system site-packages dir, and start.sh prepends the patches
directory to `PYTHONPATH` for the gateway process.
"""
from __future__ import annotations

import re


def _patch_slack_commands() -> None:
    try:
        from gateway.platforms.slack import SlackAdapter
        _orig_connect = SlackAdapter.connect

        async def _patched_connect(self):
            result = await _orig_connect(self)
            if getattr(self, "_app", None) is not None:
                @self._app.command(re.compile(".+"))
                async def _handle_unknown_command(ack, command, respond):
                    await ack()
                    cmd = command.get("command", "this command")
                    await respond(
                        f"I don't recognize `{cmd}`. "
                        "Send me a *direct message* or @mention me to chat"
                    )
            return result

        SlackAdapter.connect = _patched_connect
    except Exception:
        pass


_patch_slack_commands()
