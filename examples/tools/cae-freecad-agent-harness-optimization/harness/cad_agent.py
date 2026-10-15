# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Harbor agent that runs the CAD agent inside each task's container.

The task image holds headless FreeCAD and the agent runtime, so every trial has
its own FreeCAD and trials run in parallel. Each trial:

1. uploads ``agent/`` (prompt, model, skills) and ``run_agent.py``, and runs the
   agent for at most ``CAD_AGENT_TIMEOUT`` seconds; it reaches its model through
   the NeMo Helix inference gateway and sends its trace to Intake;
2. scores ``/app/model.FCStd`` by IoU in the container with ``scorer/``, uploaded
   only after the agent is done;
3. records that IoU on the run's Intake trace, for NeMo Compass.

The task's separate verifier grades the same file. Run from the example root::

    PYTHONPATH=harness harbor run -p evals -a cad_agent:CadAgent \\
      -m nvidia-nvidia-nemotron-3-ultra --n-attempts 2 -n 4
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Guarded so the pure helpers stay importable, and unit-testable, without Harbor.
try:  # pragma: no cover - exercised by every real run
    from harbor.agents.installed.base import BaseInstalledAgent
except ImportError:  # pragma: no cover - exercised by the tests
    BaseInstalledAgent = object  # type: ignore[assignment,misc]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HELIX = os.environ.get('NHX_BASE_URL', 'http://localhost:8080')
WORKSPACE = os.environ.get('NHX_WORKSPACE', 'default')
NEMO = [os.environ.get('NEMO_CLI') or shutil.which('nemo') or 'nemo', '--base-url', HELIX]
TIMEOUT = int(os.environ.get('CAD_AGENT_TIMEOUT', '300'))


def from_container(url: str) -> str:
    """The URL a task container uses for a service that this host serves on localhost."""
    parts = urlsplit(url)
    if parts.hostname not in ('localhost', '127.0.0.1'):
        return url
    return parts._replace(netloc=f'host.docker.internal:{parts.port or 80}').geturl()


def task_mesh(instruction: str) -> str:
    """The reference mesh the instruction names, e.g. ``/app/reference_part.obj``."""
    return re.search(r'/app/[\w.-]+\.obj', instruction).group(0)


def session_id(output: str) -> str | None:
    """The Intake session ID that ``run_agent.py`` prints."""
    match = re.search(r'^trace session (\S+)$', output, re.MULTILINE)
    return match and match.group(1)


def find_trace(session: str, wait: float = 60.0) -> dict[str, Any] | None:
    deadline = time.time() + wait
    while time.time() < deadline:
        out = subprocess.run([*NEMO, 'intake', 'traces', 'list', f'--filter.session-id={session}',
                              '--output-format', 'json'], capture_output=True, text=True)
        traces = out.returncode == 0 and json.loads(out.stdout).get('data')
        if traces:
            return traces[0]
        time.sleep(5)
    return None


def record(trace: dict[str, Any], name: str, **value: str) -> None:
    """Attach an evaluator result to the trace's root span, as Compass expects."""
    flags = [f'--{k.replace("_", "-")}={v}' for k, v in value.items()]
    subprocess.run([*NEMO, 'intake', 'evaluator-results', 'create', name, *flags,
                    f"--session-id={trace['session_id']}", f"--span-id={trace['root_span_id']}"],
                   capture_output=True)


class CadAgent(BaseInstalledAgent):
    """Deep Agents CAD agent next to headless FreeCAD, in the task container."""

    @staticmethod
    def name() -> str:
        return 'cad-agent'

    async def install(self, environment) -> None:
        # The task image already holds FreeCAD and the agent runtime.
        await self.exec_as_agent(environment,
                                 'command -v freecadcmd && python -c "import deepagents"')

    async def run(self, instruction: str, environment, context) -> None:
        await environment.upload_dir(ROOT / 'agent', '/agent')
        await environment.upload_file(HERE / 'run_agent.py', '/installed-agent/run_agent.py')
        env = {'CAD_MODEL': self.model_name or '', 'CAD_AGENT_TIMEOUT': str(TIMEOUT),
               'NHX_BASE_URL': from_container(HELIX), 'NHX_WORKSPACE': WORKSPACE}
        ran = await environment.exec(
            'python /installed-agent/run_agent.py /agent/agent.yaml '
            f'{shlex.quote(instruction)} 2>&1 | tee /logs/agent/run.log',
            env=env, timeout_sec=TIMEOUT + 120)
        await environment.upload_dir(ROOT / 'scorer', '/installed-agent/scorer')
        # Stop any FreeCAD the agent left running, then score with the image's FreeCAD
        # modules. The pattern's brackets keep pkill from matching this shell.
        scored = await environment.exec(
            "pkill -9 -if '[f]reecad'; PYTHONPATH=/opt/conda/lib python "
            f'/installed-agent/scorer/score.py /app/model.FCStd {task_mesh(instruction)}',
            timeout_sec=600)
        # Harbor merges stderr into stdout: the score is the last line, else the reason.
        output = (scored.stdout or '').strip()
        iou = float(output.split()[-1]) if scored.return_code == 0 else None
        session = session_id(ran.stdout or '')
        trace = session and await asyncio.to_thread(find_trace, session)
        reason = output.splitlines()[-1].lstrip('# ')[-300:] if output else 'scorer failed'
        context.metadata = {'trace_id': trace and trace['id'], 'iou': iou,
                            'not_scored': None if iou is not None else reason}
        if trace and iou is not None:
            record(trace, 'iou', data_type='NUMERIC', value=str(iou))
        elif trace:  # "could not measure" is not a measured zero
            record(trace, 'outcome', data_type='CATEGORICAL', string_value=f'not scored: {reason}')
