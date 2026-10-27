# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Process middleware: keep a valid model on disk, and the agent aware of time and of it.

- Save guard. Whenever /app/model.FCStd changes, it is reopened in a separate freecadcmd and
  checked: no object in error after recompute, exactly one solid, isValid, check(True),
  positive volume. A passing file is kept as the last good model. A failing file that would
  replace a good one is rolled back to the good one, and the agent is told why. A failing file
  with no good one before it stays, and the agent is told it is not a valid deliverable.
- Status line on every tool result: time used and left, and the checked state of the model
  file. Phase hints: save a first model early; near the end, no new rewrites. A FreeCAD error
  or traceback in the output is flagged even when the shell says exit code 0. A .py file just
  written or edited is flagged as not run yet.
- Look timing: the guard shares the clock and the model's checked state with the skill's
  look.py (a small JSON file in the temp dir), so look.py renders only once a valid model is
  saved and while there is time to act on what it shows. After each new valid save the status
  line says whether there is time to look and fix, or to verify and report.
- Side-feature step: the survey (sections.py all) names the body axis. At the first valid save, the guard runs sides.py on the mesh along that axis
  (1-2 s). If it finds features outside the body (arms, ribs, bosses, tabs) and sides.py has
  not been run yet, the status line names the next step: run sides.py, read SIDES.md, add the
  first feature. One reminder, and only with time left to build it.
- No silent end: when the model ends its turn with no tool call while the model file is missing
  or failed its check and time is left, it is sent back with the reason instead of ending.

Nothing here depends on the part: only the clock, the output file and the tool output.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

MODEL_FILE = '/app/model.FCStd'
GOOD_FILE = os.path.join(tempfile.gettempdir(), 'cad_last_good_model.FCStd')
LIMIT = int(os.environ.get('CAD_AGENT_TIMEOUT', '300'))
START = time.monotonic()  # loaded while the agent is built, just before it runs
FIRST_SAVE_S = 0.4 * LIMIT  # past this with no valid model: build and save now
WRAP_S = 0.75 * LIMIT       # past this: no new rewrites, keep the saved model valid
MAX_NUDGES = 3
LOOK_MIN_LEFT = 0.3 * LIMIT  # a look plus the fix it names takes ~100 s: below this, no look
MAX_LOOKS = 2
SIDES_MIN_LEFT = 75          # a side feature (sides.py, edit, re-run, save) needs about this
SIDES_PY = '/agent/skills/cad-toolkit/sides.py'
SURVEY_AXIS = re.compile(r'Most regular axis: ([xyz])\b')
STATE_FILE = os.path.join(tempfile.gettempdir(), 'cad_guard_state.json')  # read by look.py
LOOKS_FILE = os.path.join(tempfile.gettempdir(), 'cad_looks')             # written by look.py
FREECAD_ERROR = re.compile(
    r'Exception while processing file|Traceback \(most recent call last\)|Unknown exception'
    r'|Segmentation fault|Program received signal|unexpectedly terminated', re.MULTILINE)

CHECK_SCRIPT = r'''
import json, os, sys
out = {'ok': False, 'reason': ''}
try:
    import FreeCAD as App
    doc = App.openDocument(os.environ['CAD_GUARD_FILE'], True)
    for o in doc.Objects:
        o.touch()
    doc.recompute()
    bad = [o.Name for o in doc.Objects
           if 'Invalid' in o.State or 'Error' in o.State or (hasattr(o, 'isValid') and not o.isValid())]
    tops = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body'] or \
           [o for o in doc.Objects if getattr(o, 'Visibility', False) and hasattr(o, 'Shape')]
    if not tops:
        out['reason'] = 'no PartDesign Body in the file'
    else:
        s = tops[-1].Shape
        n = 0 if s.isNull() else len(s.Solids)
        vol = 0.0 if s.isNull() else s.Volume
        out.update(solids=n, volume=round(vol, 3), faces=0 if s.isNull() else len(s.Faces))
        why = []
        if bad:
            why.append('objects in error after recompute: ' + ', '.join(bad[:6]))
        if n != 1:
            why.append(f'{n} solids (need exactly 1)')
        if not s.isNull() and not s.isValid():
            why.append('shape not valid')
        if vol <= 0:
            why.append(f'volume {vol:.3g}')
        if not why:
            try:
                s.check(True)
            except Exception as e:
                why.append('check(True) failed: ' + str(e).strip().splitlines()[0][:120])
        out['ok'] = not why
        out['reason'] = '; '.join(why)
except Exception as e:
    out['reason'] = 'could not reopen: ' + str(e)[:160]
print('CAD_GUARD ' + json.dumps(out), flush=True)
'''
_SCRIPT_PATH = os.path.join(tempfile.gettempdir(), 'cad_guard_check.py')


def _elapsed() -> float:
    return time.monotonic() - START


def _looks() -> int:
    try:
        return int(open(LOOKS_FILE).read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _share(state) -> None:
    """Tell look.py the deadline and whether a valid model is saved."""
    try:
        with open(STATE_FILE + '.tmp', 'w') as fh:
            json.dump({'deadline': time.time() + LIMIT - _elapsed(), 'limit': LIMIT,
                       'look_min_left': LOOK_MIN_LEFT, 'max_looks': MAX_LOOKS,
                       'valid': bool(state and state.get('ok'))}, fh)
        os.replace(STATE_FILE + '.tmp', STATE_FILE)
    except OSError:
        pass


for _f in (STATE_FILE, LOOKS_FILE):  # a fresh run: no state left from an earlier one
    try:
        os.remove(_f)
    except OSError:
        pass
_share(None)


class SaveGuard(AgentMiddleware):
    """Checked saves with rollback, a clock and model status on every result, no silent end."""

    def __init__(self):
        super().__init__()
        self.nudges = 0
        self.seen_mtime = None   # mtime of the model file last checked
        self.state = None        # dict from the last check
        self.has_good = False
        self.prev_good = {}      # the check result of the last good file
        self.axis = None         # the survey's most regular axis (sections.py all)
        self.sides_run = False   # the agent ran sides.py itself
        self.sides_told = False

    # ---- the side-feature step -----------------------------------------------------------
    def _note_tool(self, tool: str, args: dict, output: str) -> None:
        if tool != 'execute':
            return
        cmd = str(args.get('command', ''))
        if 'sides.py' in cmd:
            self.sides_run = True
        if 'sections.py' in cmd:
            m = SURVEY_AXIS.search(output or '')
            if m:
                self.axis = m.group(1)

    def _side_count(self, axis: str) -> int:
        """Features outside the body that sides.py finds on the mesh (0 if none or it fails)."""
        if not os.path.exists('/app/frame.json') or not os.path.exists(SIDES_PY):
            return 0
        try:
            proc = subprocess.run(['python3', SIDES_PY, '--axis', axis], capture_output=True,
                                  text=True, timeout=30)
            out = proc.stdout
            return out.count('CURVED arm/loop') + out.count('STRAIGHT (rib/boss/tab)')
        except Exception:
            return 0

    def _sides_hint(self) -> str:
        if self.sides_told or self.sides_run or LIMIT - _elapsed() < SIDES_MIN_LEFT:
            return ''
        axis = self.axis or 'z'
        n = self._side_count(axis)
        if not n:
            return ''
        self.sides_told = True
        return (f'SIDE FEATURES MISSING: the mesh has {n} feature(s) outside the main body '
                f'(survey axis {axis}) that a model without them fails on. Next, before any look: '
                f'run `python3 {SIDES_PY} --axis {axis}`, read /agent/skills/cad-toolkit/SIDES.md if '
                'you have not, and add the first feature to your build script (one feature per '
                'save; a failing save is rolled back).')

    # ---- the model file ----------------------------------------------------------------
    def _check_file(self, path: str) -> dict:
        try:
            with open(_SCRIPT_PATH, 'w') as fh:
                fh.write(CHECK_SCRIPT)
            exe = shutil.which('freecadcmd') or '/opt/conda/bin/freecadcmd'
            proc = subprocess.run([exe, _SCRIPT_PATH], capture_output=True, text=True, timeout=60,
                                  env={**os.environ, 'CAD_GUARD_FILE': path})
            for line in (proc.stdout + proc.stderr).splitlines():
                if 'CAD_GUARD ' in line:
                    return json.loads(line.split('CAD_GUARD ', 1)[1])
            return {'ok': None, 'reason': 'checker gave no result'}
        except Exception as e:  # never break the run over the checker
            return {'ok': None, 'reason': f'checker failed: {e}'[:160]}

    def _refresh(self) -> str:
        """Check the model file if it changed. Returns a note about what the guard did."""
        try:
            mtime = os.stat(MODEL_FILE).st_mtime
        except OSError:
            self.seen_mtime, self.state = None, None
            if self.has_good:
                shutil.copy2(GOOD_FILE, MODEL_FILE)
                self.seen_mtime = os.stat(MODEL_FILE).st_mtime
                self.state = {**self.prev_good, 'restored': True}
                return (f'{MODEL_FILE} had disappeared; the last valid model was put back.')
            return ''
        if mtime == self.seen_mtime:
            return ''
        res = self._check_file(MODEL_FILE)
        note = ''
        if res.get('ok'):
            shutil.copy2(MODEL_FILE, GOOD_FILE)
            first = not self.has_good
            self.has_good = True
            note = self._look_hint(first)
            if first:
                side = self._sides_hint()
                note = side + (' ' + note if side and note else note) if side else note
        elif res.get('ok') is False and self.has_good:
            shutil.copy2(GOOD_FILE, MODEL_FILE)
            note = (f'SAVE REJECTED: the new {MODEL_FILE} failed the reopen check '
                    f'({res.get("reason")}), so the last valid model was restored in its place. '
                    'Fix the cause in your script and save again; never report the rejected '
                    'version as done.')
            res = {**self.prev_good, 'restored': True}
        self.seen_mtime = os.stat(MODEL_FILE).st_mtime
        if res.get('ok'):
            self.prev_good = res
        self.state = res
        _share(res)
        return note

    def _look_hint(self, first: bool) -> str:
        """After a new valid save: is there time to look and fix, or only to verify and report?"""
        left = LIMIT - _elapsed()
        looks = _looks()
        if left >= LOOK_MIN_LEFT and looks < MAX_LOOKS:
            if first:
                return ('VALID MODEL SAVED and backed up: a later failing save is rolled back to '
                        f'it. {int(left)} s left, time to look once: run look.py, read_file '
                        '/app/look.png, list the features in the mesh row your model lacks, and '
                        'fix the first difference (one change, save, verify.py).')
            return (f'Valid model saved. {int(left)} s left: verify.py; if IoU is still < 0.9, one '
                    'more look (look.py) can show what to fix next.')
        if first:
            return ('VALID MODEL SAVED and backed up. Little time left: no look, run verify.py; '
                    'make only a small numeric fix if it shows one, then report.')
        return ''

    def _model_text(self) -> str:
        st = self.state
        if st is None:
            return f'{MODEL_FILE}: not saved yet'
        if st.get('ok'):
            return (f'{MODEL_FILE}: valid on reopen (1 solid, volume {st.get("volume")}, '
                    f'{st.get("faces")} faces)')
        if st.get('ok') is None:
            return f'{MODEL_FILE}: saved, not checked ({st.get("reason")})'
        return f'{MODEL_FILE}: saved but NOT a valid deliverable ({st.get("reason")})'

    def status_line(self, output: str = '', tool: str = '', args: dict | None = None) -> str:
        note = self._refresh()
        used = _elapsed()
        left = max(0, int(LIMIT - used))
        parts = [note] if note else []
        parts.append(f'[status] {int(used)} s of {LIMIT} s used, {left} s left. {self._model_text()}.')
        if tool == 'execute' and FREECAD_ERROR.search(output or ''):
            parts.append('The output shows a Python/FreeCAD error: that script did not finish, '
                         'whatever the exit code says. Fix it and run it again.')
        path = str((args or {}).get('file_path', ''))
        if tool in ('write_file', 'edit_file') and path.endswith('.py'):
            parts.append(f'{path} is not run yet: run it now, so its errors show while there is '
                         'time to fix them.')
        good = bool(self.state and self.state.get('ok'))
        if tool == 'read_file' and not good and path.lower().endswith(('.png', '.jpg', '.jpeg')):
            parts.append('You are looking at images before any valid model is saved: that costs '
                         'turns and decides nothing yet. Build the main body from the measurements '
                         'you have and save it now; look.py then compares it with the mesh.')
        if used >= WRAP_S:
            parts.append('Near the end, and one turn of thinking can take a minute: start no new '
                         'rewrite. ' + ('Keep the valid saved model, verify it and report.' if good
                                         else 'Get the simplest valid model saved now.'))
        elif not good and used >= FIRST_SAVE_S:
            parts.append('No valid model is saved yet: build the main body only (one pad or '
                         'revolve), run it and save it now; add features after it is saved.')
        return '\n\n' + ' '.join(parts)

    # ---- tool results ------------------------------------------------------------------
    def _annotate(self, request, result):
        if not isinstance(result, ToolMessage):
            return result
        call = request.tool_call
        tool, args = call.get('name', ''), call.get('args') or {}
        content = result.content
        self._note_tool(tool, args, content if isinstance(content, str) else str(content))
        if isinstance(content, str):
            result.content = content + self.status_line(content, tool, args)
        elif isinstance(content, list):  # e.g. an image from read_file
            text = ' '.join(b.get('text', '') if isinstance(b, dict) else str(b) for b in content)
            result.content = [*content, {'type': 'text',
                                         'text': self.status_line(text, tool, args).strip()}]
        return result

    def wrap_tool_call(self, request, handler):
        return self._annotate(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._annotate(request, await handler(request))

    # ---- the end of the run ------------------------------------------------------------
    def _check_end(self, state):
        messages = state.get('messages') or []
        if not messages or not isinstance(messages[-1], AIMessage) or messages[-1].tool_calls:
            return None
        self._refresh()
        left = int(LIMIT - _elapsed())
        if (self.state and self.state.get('ok') is not False) or left < 25 \
                or self.nudges >= MAX_NUDGES:
            return None
        self.nudges += 1
        text = (f'[status] You ended your turn, but {self._model_text()}. {left} s are left. '
                'Continue with tool calls now: run (or fix and run) a build script that saves '
                f'one valid solid to {MODEL_FILE}, starting with the main body only, and check '
                'the result before you report.')
        return {'messages': [HumanMessage(content=text)], 'jump_to': 'model'}

    @hook_config(can_jump_to=['model'])
    def after_model(self, state, runtime):
        return self._check_end(state)

    @hook_config(can_jump_to=['model'])
    async def aafter_model(self, state, runtime):
        return self._check_end(state)


MIDDLEWARE = [SaveGuard()]
