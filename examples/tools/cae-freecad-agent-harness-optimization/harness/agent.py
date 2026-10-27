# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""How a CAD agent folder becomes a Deep Agents agent, shared by the eval runner
(run_agent.py) and the chat (chat/chat.py). No side effects on import.
"""
import os
import runpy
from pathlib import Path

import httpx
import openai
import yaml
from deepagents.backends import LocalShellBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain_openai import ChatOpenAI, StreamChunkTimeoutError

# The gateway failing, not the request: lost connection, time-out (incl. no streamed chunk
# for 120 s), 429 and 5xx, and a stream cut mid-answer (httpx, which openai does not wrap).
# Relay passes these through unchanged, so the type is enough.
GATEWAY_ERRORS = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError,
                  StreamChunkTimeoutError, httpx.TransportError)


# Never in the agent's shell: the gateway and the chat's endpoint, so the agent uses the
# models it is given, not others on the gateway.
ENV_DROP = ('CAD_', 'NHX_', 'CHAT_')
# A run's limit in seconds, and the longest single shell command: set by the task
# (task.toml [environment].env) or by chat.sh.
TIMEOUT = int(os.environ['CAD_AGENT_TIMEOUT'])


def chat_model(name: str, base_url: str, api_key: str = 'unused') -> ChatOpenAI:
    """A model on an OpenAI-compatible endpoint (the Helix gateway needs no key; the client
    requires one). Streamed, because the trial's egress proxy closes a connection that is idle
    for about 15 s, which cut off every longer non-streamed answer."""
    return ChatOpenAI(model=name, base_url=base_url, api_key=api_key, streaming=True, stream_usage=True)


def gateway_url(helix: str, workspace: str) -> str:
    """The OpenAI-compatible endpoint of the Helix inference gateway."""
    return f'{helix.rstrip("/")}/apis/inference-gateway/v2/workspaces/{workspace}/openai/-/v1'


def transient(error: Exception) -> bool:
    """A gateway blip worth retrying, not a request that will fail again: an error with no
    HTTP status (the stream was cut, e.g. a degenerate reply), or 424 (the upstream failed)."""
    status = getattr(error, 'status_code', None)
    return isinstance(error, GATEWAY_ERRORS) or (isinstance(error, openai.APIError) and status in (None, 424))


# The retry middleware's settings (ModelRetryMiddleware): only gateway blips, with about four
# minutes of backoff, as a backend outage or a burst of 429s costs minutes, not the run (bursts
# of 429s lasted minutes under 10 parallel runs). on_failure='error': the default ends the run
# with the error as the agent's answer, which looks like the agent stopping on its own.
RETRY = {'max_retries': 8, 'initial_delay': 2.0, 'max_delay': 60.0, 'retry_on': transient,
         'on_failure': 'error'}


def spec_of(agent_dir) -> dict:
    return yaml.safe_load((Path(agent_dir) / 'agent.yaml').read_text())


def model_name(spec: dict) -> str:
    """The agent's model: CAD_MODEL, else agent.yaml's."""
    return os.environ.get('CAD_MODEL') or spec['model']


def agent_kwargs(agent_dir, make_model, retry) -> dict:
    """create_deep_agent's arguments for an agent folder (agent.yaml, skills/, optional
    middleware.py): the model (model_name) and each subagent's from make_model, a fresh retry()
    middleware first in the agent and in every subagent, and a shell in /app whose commands
    stop after TIMEOUT s and whose environment lacks ENV_DROP."""
    spec = spec_of(agent_dir)
    subagents = [{**s, 'middleware': [retry(), *s.get('middleware', [])],
                  **({'model': make_model(s['model'])} if 'model' in s else {})}
                 for s in spec.get('subagents') or []]
    if not any(s['name'] == GENERAL_PURPOSE_SUBAGENT['name'] for s in subagents):
        # Deep Agents adds this one itself, without the agent's middleware; declared here for
        # the retry, it must also be given the skills the automatic one would have.
        subagents.append({**GENERAL_PURPOSE_SUBAGENT, 'middleware': [retry()],
                          'skills': [f'{agent_dir}/skills/']})
    # Optional: agent/middleware.py exports MIDDLEWARE, a list of Deep Agents middleware.
    extra = Path(agent_dir) / 'middleware.py'
    middleware = [retry(), *(runpy.run_path(str(extra))['MIDDLEWARE'] if extra.exists() else [])]
    return dict(
        name=spec['name'], system_prompt=spec['system_prompt'], subagents=subagents,
        skills=[f'{agent_dir}/skills/'], middleware=middleware, model=make_model(model_name(spec)),
        backend=LocalShellBackend(root_dir='/app', virtual_mode=False, timeout=TIMEOUT, env={
            k: v for k, v in os.environ.items() if not k.startswith(ENV_DROP)}))
