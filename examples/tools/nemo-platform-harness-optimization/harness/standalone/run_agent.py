# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run a NeMo agent.yaml directly on the Deep Agents SDK. No platform involved.

    python run_agent.py <agent.yaml>            # interactive
    python run_agent.py <agent.yaml> "prompt"   # one shot

Reads the same config the platform deploys, so the model, MCP servers, skills
workspace and subagents are the ones you measured.
"""
from __future__ import annotations

import asyncio, os, sys, yaml
from pathlib import Path

CONFIG = Path(sys.argv[1]).resolve()
ONESHOT = " ".join(sys.argv[2:])
GATEWAY = "http://localhost:8080/apis/inference-gateway/v2/workspaces/default/openai/-/v1"


async def build(spec: dict):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_openai import ChatOpenAI

    m = spec["models"]["default"]
    kwargs = {
        "model": ChatOpenAI(
            model=m["model"],
            base_url=m.get("base_url", GATEWAY),
            api_key=os.environ.get(m.get("api_key_env", "NEMO_AGENTS_IGW_API_KEY"), "not-used"),
        ),
        "system_prompt": spec["instructions"]["system"]["content"],
        "tools": [],
    }

    servers = (spec.get("mcp") or {}).get("servers") or {}
    if servers:
        client = MultiServerMCPClient({
            name: {"transport": "stdio", "command": s["url"], "args": s.get("args", [])}
            for name, s in servers.items()
        })
        kwargs["tools"] = list(await client.get_tools())

    # The backend root is what the agent sees as /, so skills land at /skills/.
    workspace = (spec.get("environment") or {}).get("workspace")
    if workspace:
        kwargs["backend"] = FilesystemBackend(
            root_dir=str((CONFIG.parent / workspace).resolve()), virtual_mode=True)

    subagents = (((spec.get("harnesses") or {}).get("deepagents") or {})
                 .get("settings", {}).get("deepagents") or {}).get("subagents")
    if subagents:
        kwargs["subagents"] = subagents

    return create_deep_agent(**kwargs), kwargs


async def main() -> None:
    spec = yaml.safe_load(CONFIG.read_text())
    agent, kwargs = await build(spec)
    print(f"{spec['name']}: {len(kwargs['tools'])} tools, "
          f"{len(kwargs.get('subagents') or [])} subagents, "
          f"skills_root={(spec.get('environment') or {}).get('workspace')}")

    messages: list = []
    while True:
        text = ONESHOT or input("\nyou> ").strip()
        if not text or text in {"exit", "quit"}:
            return
        messages.append({"role": "user", "content": text})
        # stream_mode="updates" is the point of running it yourself: every node
        # the graph completes is visible, not just the final answer.
        async for chunk in agent.astream({"messages": messages}, stream_mode="updates"):
            for node, update in chunk.items():
                for msg in (update or {}).get("messages", []) or []:
                    for call in getattr(msg, "tool_calls", None) or []:
                        print(f"  [{node}] -> {call['name']}({str(call['args'])[:90]})")
                    if getattr(msg, "content", None) and not getattr(msg, "tool_calls", None):
                        messages = messages + [msg]
                        print(f"\nagent> {msg.content}")
        if ONESHOT:
            return


asyncio.run(main())
