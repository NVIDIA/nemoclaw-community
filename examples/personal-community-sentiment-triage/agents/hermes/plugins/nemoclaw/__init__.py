# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
NemoClaw plugin for Hermes Agent.

Provides sandbox status tools, skill hot-reload, and a startup banner when
Hermes runs inside an OpenShell sandbox managed by NemoClaw.

Skill hot-reload: Hermes caches its skill slash-command registry in a
module-global dict on first scan. New skills dropped on disk are invisible
until the cache is cleared. This plugin provides a nemoclaw_reload_skills
tool that clears the cache and re-scans, letting the agent pick up new
skills without a gateway restart. The on_session_start hook also refreshes
skills automatically at session boundaries.
"""

import json
import os
import subprocess
import sys
import yaml


def _load_nemoclaw_config():
    """Load NemoClaw onboard config from ~/.nemoclaw/config.json."""
    config_path = os.path.expanduser("~/.nemoclaw/config.json")
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return None


def _load_hermes_config():
    """Load Hermes config.yaml from the sandbox."""
    for path in [
        os.path.expanduser("~/.hermes/config.yaml"),
        "/sandbox/.hermes/config.yaml",
    ]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return yaml.safe_load(f)
            except Exception:
                continue
    return None


def _get_sandbox_info():
    """Gather sandbox status information."""
    hermes_cfg = _load_hermes_config()
    nemoclaw_cfg = _load_nemoclaw_config()

    model = "unknown"
    provider = "custom"
    base_url = "unknown"

    if hermes_cfg:
        model_cfg = hermes_cfg.get("model", {})
        model = model_cfg.get("default", "unknown")
        provider = model_cfg.get("provider", "custom")
        base_url = model_cfg.get("base_url", "unknown")

    if nemoclaw_cfg:
        model = nemoclaw_cfg.get("model", model)
        provider = nemoclaw_cfg.get("provider", provider)

    # Check gateway health
    gateway_ok = False
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:8642/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            gateway_ok = True
    except Exception:
        pass

    return {
        "agent": "hermes",
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "gateway": "running" if gateway_ok else "stopped",
        "port": 8642,
    }


def _build_banner(info):
    # No Gateway field: at register() time Hermes's API server isn't up
    # yet, so the live health check would always report "stopped".
    lines = [
        "NemoClaw registered (Hermes)",
        "",
        f"Model:    {info['model']}",
        f"Provider: {info['provider']}",
        "Tools:    nemoclaw_status, nemoclaw_info,",
        "          nemoclaw_reload_skills",
    ]
    inner = max(len(line) for line in lines)
    horizontal = "─" * (inner + 2)

    # Border in palette green, TTY-gated and NO_COLOR-respecting — matches
    # NeMo Relay's launcher.rs:eprint_border_line.
    use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    if use_color:
        green, reset = "\x1b[38;5;112m", "\x1b[0m"
        top = f"{green}╭{horizontal}╮{reset}"
        bot = f"{green}╰{horizontal}╯{reset}"
        pipe = f"{green}│{reset}"
    else:
        top = f"╭{horizontal}╮"
        bot = f"╰{horizontal}╯"
        pipe = "│"

    rows = ["", top]
    for line in lines:
        rows.append(f"{pipe} {line.ljust(inner)} {pipe}")
    rows.append(bot)
    return "\n".join(rows)


def _handle_status(tool_input, **kwargs):
    """Handle the nemoclaw_status tool call.

    The ``**kwargs`` swallows the context fields (``task_id``, ``session_id``,
    ``tool_call_id``, ``parent_agent``) that ``tools/registry.dispatch``
    forwards to every handler — see ``handler(args, **kwargs)`` at
    ``tools/registry.py:306``. Without this, calls fail with
    ``TypeError: got an unexpected keyword argument 'task_id'`` and the
    tool surfaces an error to the user instead of running.
    """
    info = _get_sandbox_info()
    lines = [
        "NemoClaw Sandbox Status (Hermes)",
        "\u2500" * 40,
        f"  Agent:    Hermes Agent",
        f"  Gateway:  {info['gateway']}",
        f"  Model:    {info['model']}",
        f"  Provider: {info['provider']}",
        f"  Endpoint: {info['base_url']}",
        f"  API:      http://localhost:{info['port']}/v1",
    ]
    return "\n".join(lines)


def _handle_info(tool_input, **kwargs):
    """Handle the nemoclaw_info tool call \u2014 returns structured JSON.

    See ``_handle_status`` for the rationale on ``**kwargs``.
    """
    return json.dumps(_get_sandbox_info(), indent=2)


def _reload_skills():
    """Clear the Hermes skill slash-command cache and re-scan skill directories.

    Hermes's ``agent.skill_commands`` module caches discovered skills in a
    module-global dict (``_skill_commands``).  ``get_skill_commands()`` only
    scans on first call, so skills installed after gateway startup are
    invisible.  We clear the dict and call ``scan_skill_commands()`` to force
    a fresh scan.

    Returns the dict of discovered skills, or None on failure.
    """
    try:
        import agent.skill_commands as sc

        sc._skill_commands.clear()
        return sc.scan_skill_commands()
    except ImportError:
        return None
    except Exception:
        return None


def _handle_reload_skills(tool_input, **kwargs):
    """Handle the nemoclaw_reload_skills tool call.

    See ``_handle_status`` for the rationale on ``**kwargs``.
    """
    commands = _reload_skills()
    if commands is None:
        return (
            "Failed to reload skills. The agent.skill_commands module may "
            "not be available in this Hermes version."
        )

    if not commands:
        return "Skill reload complete. No skills found in skill directories."

    names = sorted(commands.keys())
    lines = [f"Skill reload complete. {len(names)} skill(s) discovered:", ""]
    for name in names:
        info = commands[name]
        desc = info.get("description", "no description")
        lines.append(f"  {name}: {desc}")
    return "\n".join(lines)


def register(ctx):
    """Register NemoClaw tools and hooks with Hermes."""

    # Register status tool
    ctx.register_tool(
        name="nemoclaw_status",
        toolset="nemoclaw",
        schema={
            "type": "function",
            "function": {
                "name": "nemoclaw_status",
                "description": (
                    "Show NemoClaw sandbox status: agent type, gateway health, "
                    "model, provider, and inference endpoint."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handle_status,
        description="NemoClaw sandbox status",
    )

    # Register info tool (structured JSON output)
    ctx.register_tool(
        name="nemoclaw_info",
        toolset="nemoclaw",
        schema={
            "type": "function",
            "function": {
                "name": "nemoclaw_info",
                "description": "Get NemoClaw sandbox info as structured JSON.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handle_info,
        description="NemoClaw sandbox info (JSON)",
    )

    # Register skill reload tool
    ctx.register_tool(
        name="nemoclaw_reload_skills",
        toolset="nemoclaw",
        schema={
            "type": "function",
            "function": {
                "name": "nemoclaw_reload_skills",
                "description": (
                    "Reload and re-discover skills from the skill directories. "
                    "Call this after new skills have been installed to make them "
                    "available as slash commands without restarting the gateway."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handle_reload_skills,
        description="Reload skills from disk without gateway restart",
    )

    def _on_session_start(**kwargs):
        _reload_skills()

    ctx.register_hook("on_session_start", _on_session_start)

    # Print at register() time, not from on_session_start: on_session_start
    # fires inside run_conversation and routes the banner into the first
    # user-message frame. try/except so a config-read failure can't block
    # tool registration above.
    try:
        print(_build_banner(_get_sandbox_info()))
    except Exception:
        pass
