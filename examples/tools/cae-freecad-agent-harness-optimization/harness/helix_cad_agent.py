# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Harbor agent that runs the CAD agent deployed on NeMo Helix.

Harbor imports this class into the host process, so a trial can reach the
FreeCAD GUI on this machine while the task container only hosts the verifier.
Each trial:

1. invokes the Helix deployment with the task instruction;
2. finds the trial's trace in Intake and records the host IoU on it;
3. uploads the saved document to ``/app/model.FCStd``, the artifact the task's
   separate verifier grades (it recomputes IoU itself, offline);
4. closes the trial's document.

Run with ``PYTHONPATH=harness harbor run -a helix_cad_agent:HelixCadAgent ...``.
One trial runs at a time on the host. A failed invocation is graded, not raised:
the verifier scores whatever document exists, and the deployment is redeployed so
a run that outlived its invocation stops. Set ``CAD_FREECAD_RESTART`` to a
command that relaunches FreeCAD (``harness/restart_freecad.sh``) to recover from
a frozen session: such a run hands over no model and scores 0.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Guarded so the pure helpers stay importable, and unit-testable, without Harbor.
try:  # pragma: no cover - exercised by every real run
    from harbor.agents.base import BaseAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext
except ImportError:  # pragma: no cover - exercised by the tests
    BaseAgent = object  # type: ignore[assignment,misc]
    BaseEnvironment = Any  # type: ignore[assignment,misc]
    AgentContext = Any  # type: ignore[assignment,misc]

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]

AGENT = os.environ.get('CAD_AGENT', 'cad-agent')
DEPLOYMENT = os.environ.get('CAD_DEPLOYMENT', 'cad-agent-deployment')
NEMO = os.environ.get('NEMO_CLI') or shutil.which('nemo') or 'nemo'
FREECAD_RPC = os.environ.get('FREECAD_RPC', 'http://127.0.0.1:9875')
MESHES = EXAMPLE_ROOT / 'meshes'
# A task names its mesh as @MESH_PATH@ (reference_part.obj) or @MESH_PATH:<file>@.
MESH_TOKEN = re.compile(r'@MESH_PATH(?::([\w.-]+))?@')
SCORER = EXAMPLE_ROOT / 'scorer' / 'score.py'
TIMEOUT = float(os.environ.get('CAD_AGENT_TIMEOUT', '1800'))
TRACE_WAIT = float(os.environ.get('CAD_AGENT_TRACE_WAIT', '300'))
MODEL_ARTIFACT = '/app/model.FCStd'
RESTART = os.environ.get('CAD_FREECAD_RESTART')
LOCK = Path(tempfile.gettempdir()) / 'cad-harness-trial.lock'


def document_name(instruction: str) -> str:
    """The FreeCAD document the task asks for, e.g. ``EvalPart``."""
    match = re.search(r'document named `([^`]+)`', instruction)
    if not match:
        raise ValueError('instruction does not name a FreeCAD document')
    return match.group(1)


def task_mesh(instruction: str) -> Path:
    """The reference mesh the task's instruction names."""
    match = MESH_TOKEN.search(instruction)
    return MESHES / ((match and match.group(1)) or 'reference_part.obj')


def pick_trace(traces: list[dict[str, Any]], started: datetime) -> dict[str, Any] | None:
    """The finished trace that began after *started* (Intake times are naive UTC)."""
    for trace in traces:
        began = datetime.fromisoformat(trace['started_at']).replace(tzinfo=timezone.utc)
        if trace.get('ended_at') and began >= started:
            return trace
    return None


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 120  # a frozen GUI must not hang the harness
        return connection


def rpc() -> xmlrpc.client.ServerProxy:
    return xmlrpc.client.ServerProxy(FREECAD_RPC, transport=_TimeoutTransport())


def nemo_json(*args: str) -> Any:
    out = subprocess.run([NEMO, *args, '--output-format', 'json'],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def record(trace: dict[str, Any], name: str, **value: str) -> None:
    """Attach an evaluator result to the trace's root span, as Compass expects."""
    flags = [f'--{k.replace("_", "-")}={v}' for k, v in value.items()]
    subprocess.run([NEMO, 'intake', 'evaluator-results', 'create', name, *flags,
                    f"--session-id={trace['session_id']}", f"--span-id={trace['root_span_id']}"],
                   capture_output=True)


def freecad(code: str) -> str:
    result = rpc().execute_code(code)
    if not result.get('success'):
        raise RuntimeError(f'FreeCAD RPC failed: {result}')
    return result.get('message', '')


def document_open(name: str) -> bool:
    return f"'{name}'" in freecad('import FreeCAD; print(list(FreeCAD.listDocuments()))')


def await_idle(timeout: float = 600.0) -> None:
    """Wait for FreeCAD's GUI dispatch, so a wedged session is not scored as a bad run."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(Exception):
            if rpc().get_rpc_status()['gui_dispatch']['state'] == 'healthy':
                return
        time.sleep(2)
    raise RuntimeError('FreeCAD did not become healthy; refusing to run a trial against it')


def restart_freecad() -> None:
    """Relaunch FreeCAD with the CAD_FREECAD_RESTART command, then wait for it."""
    subprocess.run(shlex.split(RESTART), check=True, timeout=120)
    await_idle(timeout=180)


def stop_leftover_run() -> None:
    """A timed-out invocation keeps running server-side; redeploying stops it."""
    subprocess.run([NEMO, 'agents', 'undeploy', '--agent', AGENT, '--yes'], capture_output=True)
    for _ in range(30):  # the deployment name is reusable once its record is gone
        listed = nemo_json('agents', 'deployments', 'list').get('data', [])
        if DEPLOYMENT not in {d.get('name') for d in listed}:
            break
        time.sleep(2)
    subprocess.run([NEMO, 'agents', 'deploy', '--agent', AGENT, '--name', DEPLOYMENT,
                    '--mode', 'subprocess'], capture_output=True, check=True)


@contextlib.contextmanager
def exclusive_trial():
    """One trial at a time on this host: the FreeCAD session is shared. Fails fast
    rather than waiting, because Harbor counts the wait against the agent's time."""
    with open(LOCK, 'w') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('FreeCAD is busy with another trial; run one eval job at a time')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class HelixCadAgent(BaseAgent):
    """Run the Helix CAD deployment on the host and hand its result to the verifier."""

    @staticmethod
    def name() -> str:
        return 'helix-cad-agent'

    def version(self) -> str | None:
        return '0.1.0'

    async def setup(self, environment: BaseEnvironment) -> None:
        await environment.exec('mkdir -p /app')

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        mesh = task_mesh(instruction)
        instruction = MESH_TOKEN.sub(str(mesh), instruction)
        document = document_name(instruction)
        with exclusive_trial():
            await asyncio.to_thread(self._ready)
            if document_open(document):
                raise RuntimeError(f'document {document} is already open; close it first')
            started = datetime.now(timezone.utc)
            try:
                await self._invoke(instruction, context)
                with tempfile.TemporaryDirectory() as tmp:
                    model = Path(tmp) / 'model.FCStd'
                    iou = await asyncio.to_thread(self._collect, document, model, mesh, context)
                    if model.exists():
                        await environment.upload_file(model, MODEL_ARTIFACT)
            finally:
                with contextlib.suppress(Exception):
                    freecad(f'import FreeCAD\nif {document!r} in FreeCAD.listDocuments():\n'
                            f'    FreeCAD.closeDocument({document!r})')
        # Outside the lock: the trace arrives after the run and does not need FreeCAD.
        trace = await asyncio.to_thread(self._await_trace, started)
        context.metadata['trace_id'] = trace and trace['id']
        if trace is not None:
            if iou is not None:
                record(trace, 'iou', data_type='NUMERIC', value=str(iou))
            else:
                record(trace, 'outcome', data_type='CATEGORICAL',
                       string_value=f"not scored: {context.metadata.get('not_scored', 'no model')}")

    @staticmethod
    def _ready() -> None:
        try:
            await_idle(timeout=30 if RESTART else 600)
            freecad('pass')  # "healthy" status alone missed a GUI blocked after a crash
        except RuntimeError:
            if not RESTART:
                raise
            restart_freecad()

    async def _invoke(self, instruction: str, context: AgentContext) -> None:
        completed = await asyncio.to_thread(
            subprocess.run,
            [NEMO, 'agents', 'invoke', '--agent-deployment', DEPLOYMENT,
             '--timeout', str(int(TIMEOUT)), '--input', instruction],
            capture_output=True, text=True, timeout=TIMEOUT + 60,
        )
        context.metadata = {'invoke_returncode': completed.returncode}
        if completed.returncode != 0:  # the agent failed; the verifier grades what is left
            context.metadata['invoke_error'] = (completed.stderr + completed.stdout).strip()[-600:]
            await asyncio.to_thread(stop_leftover_run)

    def _collect(self, document: str, model: Path, mesh: Path, context: AgentContext) -> float | None:
        """Save the document for the verifier and score it on the host."""
        try:
            await_idle(timeout=120 if RESTART else 600)
        except RuntimeError:
            if not RESTART:
                raise
            context.metadata['not_scored'] = 'FreeCAD stopped responding (frozen or crashed)'
            restart_freecad()  # nothing to hand over: the verifier fails the run
            return None
        if document_open(document):
            freecad(f'import FreeCAD\nFreeCAD.getDocument({document!r}).saveCopy({str(model)!r})')
        scored = subprocess.run([sys.executable, str(SCORER), document, str(mesh)],
                                capture_output=True, text=True)
        iou = float(scored.stdout) if scored.returncode == 0 else None
        if iou is None:
            context.metadata['not_scored'] = scored.stderr.strip().lstrip('# ') or 'scorer failed'
        context.metadata.update({'document': document, 'iou': iou})
        return iou

    def _await_trace(self, started: datetime) -> dict[str, Any] | None:
        deadline = time.time() + TRACE_WAIT
        while time.time() < deadline:
            traces = nemo_json('intake', 'traces', 'list', f'--filter.agent-name={AGENT}',
                               '--sort=-started_at', '--page-size=5').get('data', [])
            trace = pick_trace(traces, started)
            if trace:
                return trace
            time.sleep(5)
        return None
