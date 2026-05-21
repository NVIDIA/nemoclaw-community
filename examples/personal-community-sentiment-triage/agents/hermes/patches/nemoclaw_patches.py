# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw runtime patches for the Hermes sandbox.
#
# Bundled into the image at /usr/local/lib/nemoclaw-patches/nemoclaw_patches.py
# and chain-loaded by the neighboring sitecustomize.py (which Python imports
# preferentially because /usr/local/lib/nemoclaw-patches/ is first on
# PYTHONPATH).
#
# Slack catch-all slash command — Hermes only registers "/hermes" as its bolt
# command handler. Any workspace-specific command name (e.g. /my-assistant)
# produces an "Unhandled request" warning. After SlackAdapter connects,
# register a catch-all that routes every other slash command through the same
# _handle_slash_command path.
import re as _re


def _patch_slack_commands() -> None:
    try:
        from gateway.platforms.slack import SlackAdapter
        _orig_connect = SlackAdapter.connect

        async def _patched_connect(self):
            result = await _orig_connect(self)
            if getattr(self, "_app", None) is not None:
                @self._app.command(_re.compile(".+"))
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
