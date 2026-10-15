# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the CAD agent inside a task container, next to headless FreeCAD.

Builds a Deep Agents agent from ``agent.yaml`` with a real shell in ``/app``,
gives it the task for at most ``CAD_AGENT_TIMEOUT`` seconds, and traces the run
with NeMo Relay: one ATIF trajectory, posted to Intake, whose session ID it
prints. ``cad_agent.py`` uploads and starts this script.

    python run_agent.py AGENT_YAML INSTRUCTION
"""

import asyncio
import os
import sys

import yaml
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from nemo_relay import ScopeType, plugin, scope
from nemo_relay.integrations.deepagents import add_nemo_relay_integration

TIMEOUT = int(os.environ.get('CAD_AGENT_TIMEOUT', '300'))
# A Helix API, e.g. HELIX % 'intake'; cad_agent.py passes the URL as the container sees it.
HELIX = (f"{os.environ['NHX_BASE_URL']}/apis/%s/v2/workspaces/"
         f"{os.environ.get('NHX_WORKSPACE', 'default')}")


def relay_config(name: str, model: str, tools: list[dict], intake: str) -> dict:
    """One ATIF trajectory per run, carrying the agent's name, model and tool schemas."""
    atif = {'enabled': True, 'agent_name': name, 'model_name': model, 'tool_definitions': tools,
            'storage': [{'type': 'http', 'endpoint': intake}]}
    return {'version': 1, 'components': [
        {'kind': 'observability', 'enabled': True, 'config': {'version': 3, 'atif': atif}}]}


async def main(spec_path: str, instruction: str) -> None:
    with open(spec_path) as f:
        spec = yaml.safe_load(f)
    name, model = spec['name'], os.environ.get('CAD_MODEL') or spec['models']['default']['model']
    agent = create_deep_agent(**add_nemo_relay_integration(
        name=name, system_prompt=spec['instructions']['system']['content'],
        subagents=spec.get('subagents'),
        # The Helix inference gateway needs no key; the client requires one.
        model=ChatOpenAI(model=model, base_url=HELIX % 'inference-gateway' + '/openai/-/v1',
                         api_key='unused', max_retries=6),  # ride out gateway blips
        backend=LocalShellBackend(root_dir='/app', virtual_mode=False, inherit_env=True,
                                  timeout=TIMEOUT)))
    tools = [convert_to_openai_tool(t)['function']
             for t in agent.nodes['tools'].bound.tools_by_name.values()]
    async with plugin.plugin(relay_config(name, model, tools, HELIX % 'intake' + '/ingest/atif')):
        with scope.scope(name, ScopeType.Agent) as run:
            print(f'trace session {run.uuid}', flush=True)  # the Intake session ID
            try:
                await asyncio.wait_for(agent.ainvoke(
                    {'messages': [{'role': 'user', 'content': instruction}]}), TIMEOUT)
            except TimeoutError:
                print(f'stopped after {TIMEOUT} s', file=sys.stderr)


if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:3]))
