# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw site customization — NeMo-Flow patched Hermes base image.
#
# Loaded by Python at startup via the sitecustomize convention (site module).
# Installed into the NeMo-Flow base image at build time.
#
# Patch 1 — httpx transport fix: Hermes creates httpx.Client(transport=HTTPTransport(...))
# for TCP keepalives. A custom transport bypasses HTTPS_PROXY env-var routing,
# so Hermes cannot reach inference.local (only reachable via the OpenShell L7
# proxy). Strip transport= when HTTPS_PROXY is set so httpx falls back to its
# default proxy-aware transport.
#
# Patch 2 — NeMo-Flow observability: on_session_end is intentionally a no-op in
# nemo_flow (pitfall P-02 — avoids premature finalization for long-lived CLI
# sessions). In the gateway, every run_conversation call IS a complete session
# regardless of platform, so we finalize immediately on every on_session_end.
# on_session_finalize never fires from the API server or native platform paths.
#
# Patch 3 — Slack catch-all slash command: Hermes only registers "/hermes" as
# its bolt command handler. Any workspace-specific command name (e.g.
# /my-assistant) produces an "Unhandled request" warning. After SlackAdapter
# connects, register a catch-all that routes every other slash command through
# the same _handle_slash_command path.
import os as _os
import re as _re
import sys as _sys
import importlib.abc as _iabc
import importlib.util as _iutil


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
                        "Send me a *direct message* or @mention me a to chat"
                    )
            return result

        SlackAdapter.connect = _patched_connect
    except Exception:
        pass


_patch_httpx()
_patch_slack_commands()


class _PatchingLoader(_iabc.Loader):
    def __init__(self, real: _iabc.Loader) -> None:
        self._real = real

    def create_module(self, spec):  # type: ignore[override]
        m = getattr(self._real, "create_module", None)
        return m(spec) if m else None

    def exec_module(self, mod) -> None:  # type: ignore[override]
        self._real.exec_module(mod)
        def _gateway_session_end(session_id: str = "", platform: str = "", **_kw) -> None:
            if session_id and getattr(mod, "_NEMO_FLOW_OK", False):
                try:
                    mod._finalize(session_id, platform or "session_end")
                except Exception:
                    pass
        mod.on_session_end = _gateway_session_end


class _NemoFlowPatcher(_iabc.MetaPathFinder):
    def find_spec(self, fullname: str, path, target=None):  # type: ignore[override]
        if fullname != "plugins.nemo_flow.observability":
            return None
        _sys.meta_path.remove(self)
        spec = _iutil.find_spec(fullname)
        if spec is not None:
            spec.loader = _PatchingLoader(spec.loader)
        return spec


_sys.meta_path.insert(0, _NemoFlowPatcher())
