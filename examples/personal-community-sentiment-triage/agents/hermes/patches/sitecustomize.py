# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw site customization — standard Hermes base image.
#
# Loaded by Python at startup via the sitecustomize convention (site module).
# Installed into the base image at build time; applies to all Python processes
# in the container (Hermes gateway, Outlook bridge, etc.).
#
# Patch 1 — httpx transport fix: Hermes creates httpx.Client(transport=HTTPTransport(...))
# for TCP keepalives. A custom transport bypasses HTTPS_PROXY env-var routing,
# so Hermes cannot reach inference.local (only reachable via the OpenShell L7
# proxy). Strip transport= when HTTPS_PROXY is set so httpx falls back to its
# default proxy-aware transport.
#
# Patch 2 — Slack catch-all slash command: Hermes only registers "/hermes" as
# its bolt command handler. Any workspace-specific command name (e.g.
# /my-assistant) produces an "Unhandled request" warning and Slack shows
# nothing to the user. After SlackAdapter connects, register a catch-all that
# responds with a brief hint so the user knows how to reach the bot.
import os as _os
import re as _re


def _patch_httpx() -> None:
    try:
        import httpx
        _orig = httpx.Client.__init__
        def _fixed(self, *a, **kw):
            if "transport" in kw and (
                _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            ):
                del kw["transport"]
            _orig(self, *a, **kw)
        httpx.Client.__init__ = _fixed
    except Exception:
        pass


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
                        "Send me a *direct message* to chat, "
                        "or use `/hermes <your message>` in any channel."
                    )
            return result

        SlackAdapter.connect = _patched_connect
    except Exception:
        pass


_patch_httpx()
_patch_slack_commands()
