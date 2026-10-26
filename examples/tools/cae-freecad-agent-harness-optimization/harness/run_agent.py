# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the CAD agent in a task container: Deep Agents with a shell in /app, traced
with NeMo Relay to Intake.  python run_agent.py AGENT_DIR INSTRUCTION

The agent's model and each subagent's `model:` are names on the Helix inference gateway.
"""

import asyncio
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import openai
import yaml
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI, StreamChunkTimeoutError
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
# How the run ended, for publish.py (a run lost to the gateway is VOID, not graded).
OUTCOME = Path('/logs/agent/outcome.json')
# The gateway failing, not the request: lost connection, time-out (incl. no streamed chunk
# for 120 s), 429 and 5xx, and a stream cut mid-answer (httpx, which openai does not wrap).
# Relay passes these through unchanged, so the type is enough.
GATEWAY_ERRORS = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError,
                  StreamChunkTimeoutError, httpx.TransportError)
# A run that waited this share of its limit on the gateway lost too much to count: VOID.
GATEWAY_LOSS_S = 0.15 * TIMEOUT


def transient(error: Exception) -> bool:
    """A gateway blip worth retrying, not a request that will fail again: an error with no
    HTTP status (the stream was cut, e.g. a degenerate reply), or 424 (the upstream failed)."""
    status = getattr(error, 'status_code', None)
    return isinstance(error, GATEWAY_ERRORS) or (isinstance(error, openai.APIError) and status in (None, 424))


class GatewayRetry(ModelRetryMiddleware):
    """The retry, timing how long the run had a model call waiting on the gateway (from a failed
    attempt to the one that got through): calls waiting at once, as parallel subagents do, count once."""

    waited, waiting, since = 0.0, 0, 0.0

    @classmethod
    def mark(cls, step: int, at: float) -> None:
        if step > 0 and cls.waiting == 0:
            cls.since = at
        cls.waiting += step
        if step < 0 and cls.waiting == 0:
            cls.waited += at - cls.since

    @classmethod
    def total(cls) -> float:
        return cls.waited + (time.monotonic() - cls.since if cls.waiting else 0.0)

    async def awrap_model_call(self, request, handler):
        waiting = False

        async def attempt(req):
            nonlocal waiting
            start = time.monotonic()
            try:
                response = await handler(req)
            except Exception as error:
                if not waiting and transient(error):
                    waiting = True
                    GatewayRetry.mark(1, start)
                raise
            if waiting:
                waiting = False
                GatewayRetry.mark(-1, start)
            return response

        try:
            return await super().awrap_model_call(request, attempt)
        finally:
            if waiting:  # the retries ran out, or the run was stopped
                GatewayRetry.mark(-1, time.monotonic())


def stop_descendants() -> None:
    """Stop every process this run started, shell commands left running included, so nothing
    changes the workspace after the limit."""
    children = {}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            ppid = int(stat.read_text().rsplit(')', 1)[1].split()[1])
        except (OSError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(stat.parent.name))
    todo = list(children.get(os.getpid(), []))
    while todo:
        pid = todo.pop()
        todo += children.get(pid, [])
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def gateway_model(name: str) -> ChatOpenAI:
    # The Helix inference gateway needs no key; the client requires one. Streamed, because
    # the trial's egress proxy closes a connection that is idle for about 15 s, which cut
    # off every longer non-streamed answer.
    return ChatOpenAI(model=name, base_url=GATEWAY, api_key='unused', streaming=True,
                      stream_usage=True)


async def main(agent_dir: str, instruction: str) -> None:
    spec = yaml.safe_load((Path(agent_dir) / 'agent.yaml').read_text())
    model = os.environ.get('CAD_MODEL') or spec['model']
    # Harness, not agent: ride out model-gateway blips and a busy backend, in the agent and
    # in every subagent. The OpenAI client's own two retries are spent within seconds, and
    # the error then ended the run.
    def retry():
        # About four minutes of backoff: a backend outage or a burst of 429s costs minutes, not
        # the run (bursts of 429s lasted minutes under 10 parallel runs).
        # on_failure='error': the default ends the run with the error as the agent's answer,
        # which looks like the agent stopping on its own; raised, main() records the run as
        # ended by the gateway, and publish.py treats it as void.
        return GatewayRetry(max_retries=8, initial_delay=2.0, max_delay=60.0,
                            retry_on=transient, on_failure='error')

    subagents = [{**s, 'middleware': [retry(), *s.get('middleware', [])],
                  **({'model': gateway_model(s['model'])} if 'model' in s else {})}
                 for s in spec.get('subagents') or []]
    if not any(s['name'] == GENERAL_PURPOSE_SUBAGENT['name'] for s in subagents):
        # Deep Agents adds this one itself, without the agent's middleware; declared here for
        # the retry, it must also be given the skills the automatic one would have.
        subagents.append({**GENERAL_PURPOSE_SUBAGENT, 'middleware': [retry()],
                          'skills': [f'{agent_dir}/skills/']})
    # Optional: agent/middleware.py exports MIDDLEWARE, a list of Deep Agents middleware.
    extra = Path(agent_dir) / 'middleware.py'
    middleware = [retry(), *(runpy.run_path(str(extra))['MIDDLEWARE'] if extra.exists() else [])]
    agent = create_deep_agent(**add_nemo_relay_integration(
        name=spec['name'], system_prompt=spec['system_prompt'], subagents=subagents,
        skills=[f'{agent_dir}/skills/'], middleware=middleware, model=gateway_model(model),
        # The agent's shell gets the container's environment without the Helix settings,
        # so the agent uses the models it is given, not others on the gateway.
        backend=LocalShellBackend(root_dir='/app', virtual_mode=False, timeout=TIMEOUT, env={
            k: v for k, v in os.environ.items() if not k.startswith(('CAD_', 'NHX_'))})))
    tools = [convert_to_openai_tool(t)['function']
             for t in agent.nodes['tools'].bound.tools_by_name.values()]
    atif = AtifConfig(enabled=True, agent_name=spec['name'], model_name=model,
                      tool_definitions=tools,
                      # Relay's default 3 s is shorter than Intake takes to ingest a long trace,
                      # and 60 s still lost long traces while Intake was busy with others.
                      storage=[HttpStorageConfig(endpoint=INTAKE, timeout_millis=180_000)])
    config = PluginConfig(components=[ComponentSpec(config=ObservabilityConfig(atif=atif))])
    outcome = {'trace': None, 'ended': 'done', 'trace_delivered': True}
    try:
        async with plugin.activate(config):
            with scope.scope(spec['name'], ScopeType.Agent) as run:
                outcome['trace'] = str(run.uuid)
                print(f'trace {run.uuid}', flush=True)  # the Intake trace ID, for publish.py
                try:
                    await asyncio.wait_for(agent.ainvoke(
                        {'messages': [{'role': 'user', 'content': instruction}]}), TIMEOUT)
                except (*GATEWAY_ERRORS, openai.APIError) as error:  # before TimeoutError: a
                    # stream time-out is one. The retries are spent, or the key's budget (422);
                    # any other request error is the run's.
                    if not (transient(error) or 'budget' in str(error)):
                        raise
                    outcome['ended'] = 'gateway'
                    print(f'gateway: {error!r}', flush=True)
                except TimeoutError:
                    outcome['ended'] = 'timeout'
                    print(f'stopped after {TIMEOUT} s', flush=True)
    except RuntimeError as error:
        # Relay raises at teardown when Intake did not take the trace. The run itself is
        # done and is graded as usual; say so, and still stop FreeCAD below.
        if 'delivery' not in str(error):
            outcome['ended'] = 'crash'
            raise
        outcome['trace_delivered'] = False
        print(f'trace not delivered: {error}', flush=True)
    except BaseException:
        outcome['ended'] = 'crash'
        raise
    finally:
        # Whatever happened: stop everything the run started, so nothing is saved after the
        # limit, and record how the run ended (lost to the gateway if it waited too long).
        stop_descendants()
        subprocess.run(['pkill', '-9', 'freecadcmd'])  # one left running in the background
        waited = GatewayRetry.total()
        outcome['gateway_wait_s'] = round(waited)
        if waited >= GATEWAY_LOSS_S:
            outcome['ended'] = 'gateway'
        OUTCOME.write_text(json.dumps(outcome))
    os._exit(0)  # without waiting for a shell command still running

if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:3]))
