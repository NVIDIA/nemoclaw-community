# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The agent side of the web chat (web.py), inside the cad-env image: the agent built as the
eval builds it, one task per message in its own process, and a mesh turned into the job's
reference."""
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from deepagents import create_deep_agent
from langchain.agents.middleware import ModelRetryMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness'))  # /harness in the container
from agent import RETRY, TIMEOUT, agent_kwargs, chat_model, gateway_url, model_name, spec_of  # noqa: E402

# Any OpenAI-compatible endpoint; the Helix inference gateway by default (it needs no key).
BASE_URL = os.environ.get('CHAT_BASE_URL') or gateway_url(
    os.environ.get('CAD_HELIX_URL', 'http://host.docker.internal:8080'), os.environ.get('NHX_WORKSPACE', 'default'))
API_KEY = os.environ.get('CHAT_API_KEY') or 'unused'
APP = Path('/app')
MODEL = APP / 'model.FCStd'
STARTUP = 120  # s for a task process to build its agent, before its own clock starts
# Task processes fork from a clean server process that has the agent stack imported once, so a
# message does not pay seconds of imports, and inherits nothing from the web server's threads.
SPAWN = multiprocessing.get_context('forkserver')
SPAWN.set_forkserver_preload(['deepagents', 'langchain_openai', 'agent'])


def build(agent_dir: Path):
    """The agent as the eval builds it (harness/agent.py), on this chat's endpoint."""
    return create_deep_agent(**agent_kwargs(agent_dir, lambda name: chat_model(name, BASE_URL, API_KEY),
                                            lambda: ModelRetryMiddleware(**RETRY)))


def check_model(agent_dir: Path) -> None:
    """Stop at once, not at the first message, when the agent or a subagent has no model."""
    spec = spec_of(agent_dir)
    names = [model_name(spec), *(s['model'] for s in spec.get('subagents') or [] if 'model' in s)]
    if any('REPLACE_WITH' in n for n in names):
        sys.exit(f'No model for {agent_dir}: set CAD_MODEL to a model on your gateway '
                 '(nemo models list --all-pages), or set model: in its agent.yaml (and its subagents\').')


def steps(message):
    """The chat's view of one message as (kind, text): a line per tool call ('call'), the last
    lines of each tool result ('result'), the agent's text in full ('text'), and each image
    the agent reads, as the model got it ('image', a data URL)."""
    if message.type == 'ai':  # its text first: the agent says what it is about to do
        if isinstance(message.content, str) and message.content.strip():
            yield 'text', message.content.strip()
        for call in getattr(message, 'tool_calls', None) or []:
            args = call.get('args') or {}
            yield 'call', f"> {call['name']} {str(args.get('command') or args)[:300]}"
    elif message.type == 'tool':
        blocks = message.content if isinstance(message.content, list) else []
        images = [b for b in blocks if isinstance(b, dict) and b.get('type') == 'image' and b.get('base64')]
        if images:  # read_file of an image: Deep Agents hands the model the image itself
            yield 'result', f"image {message.additional_kwargs.get('read_file_path', '')}"
            for b in images:
                yield 'image', f"data:{b.get('mime_type') or 'image/png'};base64,{b['base64']}"
        else:
            lines = str(message.content).strip().splitlines()
            yield 'result', ' | '.join(lines[-3:])[:300]


def turn(agent_dir: Path, history: list, prompt: str):
    """One task, as (kind, text) steps: 'ready' once the agent is built (its clock starts
    there), its steps as they happen, and last ('history', conversation): history, the prompt
    and this task's last text (text only: no tool calls, clock stamps or notes). The agent is
    rebuilt per task, so its middleware's clock starts anew."""
    asked = [*history, {'role': 'user', 'content': prompt}]
    agent = build(agent_dir)
    yield 'ready', ''
    shown, answer = None, ''  # shown by id: middleware may summarize (shrink) the list
    for state in agent.stream({'messages': asked}, stream_mode='values'):
        if shown is None:  # the first state is the input
            shown = {m.id for m in state['messages']}
        for message in state['messages']:
            if message.id not in shown:
                shown.add(message.id)
                for kind, text in steps(message):
                    if kind == 'text':
                        answer = text
                    yield kind, text
    yield 'history', [*asked, *([{'role': 'assistant', 'content': answer}] if answer else [])]


def _task(pipe, agent_dir: str, history: list, prompt: str) -> None:
    """The task process, in its own session: stopping the group stops all it started."""
    os.setsid()
    try:
        for item in turn(Path(agent_dir), history, prompt):
            pipe.send(item)
    except Exception as e:  # noqa: BLE001  (shown in the chat, which continues)
        pipe.send(('note', f'{type(e).__name__}: {e}'))
        pipe.send(('history', None))


class Task:
    """One message's task in its own process group. steps() yields (kind, text) until the task
    ends, its TIMEOUT s have passed (counted from 'ready', as the agent's own clock), or alive()
    is false; history is then the new conversation if the task completed, else None. The caller
    stops it."""

    def __init__(self, agent_dir: Path, history: list, prompt: str):
        self.pipe, child = SPAWN.Pipe(duplex=False)
        self.process = SPAWN.Process(target=_task, args=(child, str(agent_dir), history, prompt), daemon=True)
        self.process.start()
        child.close()
        self.history, self.started, self.deadline = None, False, time.monotonic() + STARTUP

    def steps(self, alive=lambda: True):
        try:
            while alive():
                if time.monotonic() > self.deadline:
                    yield 'note', (f'stopped after {TIMEOUT} s' if self.started
                                   else f'the agent did not start within {STARTUP} s')
                    return
                if self.pipe.poll(1):
                    kind, value = self.pipe.recv()
                    if kind == 'ready':
                        self.started, self.deadline = True, time.monotonic() + TIMEOUT
                    elif kind == 'history':
                        self.history = value
                        return
                    else:
                        yield kind, value
        except EOFError:
            yield 'note', 'the task ended unexpectedly'

    def stop(self) -> None:
        """Kill the task's process group (its shell commands and FreeCAD too) and wait for it."""
        with suppress(ProcessLookupError):  # no group yet if it had not reached setsid()
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.kill()
        self.process.join()


def to_obj(src: Path, dst: Path) -> None:
    """Write a mesh (OBJ/STL) or a model (.FCStd) as an OBJ mesh, with FreeCAD (fc.py)."""
    tmp = dst.with_name(f'.{dst.stem}.part.obj')
    try:
        tmp.unlink(missing_ok=True)  # never a partial file from a run that was killed
        run = subprocess.run(['freecadcmd', str(Path(__file__).with_name('fc.py'))], capture_output=True,
                             text=True, timeout=300, env={**os.environ, 'SRC': str(src), 'DST': str(tmp)})
        # freecadcmd exits 0 when the script raises; it prints "Exception while processing file: ... [why]"
        why = [line.rsplit('[', 1)[-1].rstrip(']') for line in (run.stdout + run.stderr).splitlines()
               if 'Exception while processing' in line]
        if run.returncode or why or not tmp.exists():
            raise RuntimeError(f'FreeCAD could not read {src.name}: {why[0] if why else run.returncode}')
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)


def ingest(mesh: Path) -> None:
    """A new mesh starts a new job in an empty /app, as each eval run does: the earlier job's
    files move to /app/.jobs/<time>/, and the mesh becomes /app/reference.obj (the mesh itself
    is left as it is)."""
    to_obj(mesh, Path('/tmp/reference.obj'))
    old = [p for p in APP.iterdir() if p.name != '.jobs']
    if old:
        (APP / '.jobs').mkdir(exist_ok=True)
        keep = Path(tempfile.mkdtemp(prefix=time.strftime('%Y%m%d-%H%M%S-'), dir=APP / '.jobs'))  # unique
        for p in old:
            p.replace(keep / p.name)
    shutil.move('/tmp/reference.obj', APP / 'reference.obj')  # /tmp and /app are different file systems
