# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""A clock for the agent. The model cannot see wall time, and the run is stopped after
CAD_AGENT_TIMEOUT seconds (300) wherever it is, so runs ended mid-build with no report.

- Every tool result ends with `[clock: N s of 300 used]`.
- A shell command's timeout is capped so it returns before the stop, leaving time to report.
- From WRAP_AT seconds on, the model is told once to stop building and report.
"""
import os
import time

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage

START = time.monotonic()            # loaded by run_agent.py when the run starts
LIMIT = int(os.environ.get('CAD_AGENT_TIMEOUT', '300'))
WRAP_AT = LIMIT - 60                 # leave time for one verify or one last report
RESERVE = 25                         # seconds kept free after any shell command


def _used():
    return int(time.monotonic() - START)


def _stamp(result):
    if isinstance(result, ToolMessage) and isinstance(result.content, str):
        result.content = f'{result.content}\n[clock: {_used()} s of {LIMIT} used]'
    return result


def _cap(request):
    call = request.tool_call
    if call.get('name') == 'execute':
        left = max(LIMIT - RESERVE - _used(), 5)
        args = dict(call.get('args') or {})
        try:
            t = int(float(args.get('timeout') or left))
        except (TypeError, ValueError):
            t = left
        args['timeout'] = min(t, left)
        call['args'] = args
    return request


WRAP_NOTE = (f'[clock] About 60 s of the {LIMIT} s run are left. Stop building now. /app/model.FCStd '
             'holds the best valid model saved so far. Report now, without new tool calls: the '
             'features, the named dimensions and the last SAVED / VERDICT numbers you have seen.')


class Clock(AgentMiddleware):
    def __init__(self):
        super().__init__()
        self.warned = False

    def wrap_tool_call(self, request, handler):
        return _stamp(handler(_cap(request)))

    async def awrap_tool_call(self, request, handler):
        return _stamp(await handler(_cap(request)))

    def _note(self, state):
        if not self.warned and _used() >= WRAP_AT:
            self.warned = True
            return {'messages': [HumanMessage(content=WRAP_NOTE)]}
        return None

    def before_model(self, state, runtime):
        return self._note(state)

    async def abefore_model(self, state, runtime):
        return self._note(state)


MIDDLEWARE = [Clock()]
