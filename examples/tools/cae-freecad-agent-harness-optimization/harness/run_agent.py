# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the CAD agent in a task container: Deep Agents with a shell in /app, traced
with NeMo Relay to Intake.  python run_agent.py AGENT_DIR INSTRUCTION
"""

import asyncio
import os
import runpy
import subprocess
import sys
from pathlib import Path

import yaml
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from nemo_relay import ScopeType, plugin, scope
from nemo_relay.integrations.deepagents import add_nemo_relay_integration
from nemo_relay.observability import (AtifConfig, ComponentSpec, HttpStorageConfig,
                                      ObservabilityConfig)
from nemo_relay.plugin import PluginConfig

# Set by the task (task.toml [environment].env): the run's time limit, and NeMo Helix
# as the container reaches it (inference gateway for the model, Intake for traces).
TIMEOUT = int(os.environ['CAD_AGENT_TIMEOUT'])
HELIX = os.environ['CAD_HELIX_URL'].rstrip('/')
WORKSPACE = os.environ.get('NHX_WORKSPACE', 'default')
GATEWAY = f'{HELIX}/apis/inference-gateway/v2/workspaces/{WORKSPACE}/openai/-/v1'
INTAKE = f'{HELIX}/apis/intake/v2/workspaces/{WORKSPACE}/ingest/atif'


async def main(agent_dir: str, instruction: str) -> None:
    spec = yaml.safe_load((Path(agent_dir) / 'agent.yaml').read_text())
    model = os.environ.get('CAD_MODEL') or spec['model']
    # Optional: agent/middleware.py exports MIDDLEWARE, a list of Deep Agents middleware.
    extra = Path(agent_dir) / 'middleware.py'
    middleware = runpy.run_path(str(extra))['MIDDLEWARE'] if extra.exists() else []
    agent = create_deep_agent(**add_nemo_relay_integration(
        name=spec['name'], system_prompt=spec['system_prompt'], subagents=spec.get('subagents'),
        skills=[f'{agent_dir}/skills/'], middleware=middleware,
        # The Helix inference gateway needs no key; the client requires one.
        model=ChatOpenAI(model=model, base_url=GATEWAY, api_key='unused', max_retries=6),
        backend=LocalShellBackend(root_dir='/app', virtual_mode=False, inherit_env=True,
                                  timeout=TIMEOUT)))
    tools = [convert_to_openai_tool(t)['function']
             for t in agent.nodes['tools'].bound.tools_by_name.values()]
    atif = AtifConfig(enabled=True, agent_name=spec['name'], model_name=model,
                      tool_definitions=tools, storage=[HttpStorageConfig(endpoint=INTAKE)])
    config = PluginConfig(components=[ComponentSpec(config=ObservabilityConfig(atif=atif))])
    async with plugin.plugin(config):
        with scope.scope(spec['name'], ScopeType.Agent) as run:
            print(f'trace {run.uuid}', flush=True)  # the Intake trace ID, for publish.py
            try:
                await asyncio.wait_for(agent.ainvoke(
                    {'messages': [{'role': 'user', 'content': instruction}]}), TIMEOUT)
            except TimeoutError:
                print(f'stopped after {TIMEOUT} s', flush=True)
    # Time is up and the trace is sent: stop any FreeCAD still running, so nothing is
    # saved after the limit, and exit without waiting for its shell command.
    subprocess.run(['pkill', '-9', 'freecadcmd'])
    os._exit(0)


if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:3]))
