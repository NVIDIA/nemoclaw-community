# SPDX-License-Identifier: Apache-2.0

"""Collect provider-published reasoning without changing effort or replaying it.

An opaque per-call marker crosses the native runtime, then is removed at the
credential proxy before inference. Only registered live markers can select a
mission. Response bytes and tool messages pass through unchanged. No prompts,
keys, encrypted reasoning or final-answer reconstructions are stored here.
NVIDIA GPT 6+ calls opt in to public summaries, within the same request.
"""
import codecs
import contextvars
import copy
import json
import re
import secrets
import sqlite3
import threading
import time

import nvidia_endpoints

MAX_TEXT = 24000
MAX_JOB_TEXT = 192000
MAX_CALLS = 48
MAX_TURNS = 32
MARKER = re.compile(r'\[\[bac-observe:([a-f0-9]{32})\]\]\n')
_current = contextvars.ContextVar('model_reasoning', default=None)
_active = {}
_lock = threading.RLock()


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS model_reasoning (
          id TEXT PRIMARY KEY, job TEXT NOT NULL, started REAL NOT NULL, record TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS reasoning_job ON model_reasoning(job,started);
        CREATE TRIGGER IF NOT EXISTS delete_job_reasoning AFTER DELETE ON jobs BEGIN
          DELETE FROM model_reasoning WHERE job=old.id;
        END;
    ''')


class Capture:
    def __init__(self, studio, job, role, name, phase):
        self.studio, self.job = studio, job
        self.key = secrets.token_hex(16)
        self.record = dict(id=self.key, role=role, name=name, phase=phase,
                           started=time.time(), status='collecting', turns=[])
        self.chars = 0
        self.live_model = None
        self.current_turn = None
        self.previous_chars = 0
        try:
            with sqlite3.connect(studio.db_path, timeout=.1) as db:
                self.previous_chars = db.execute("SELECT coalesce(sum(json_extract(record,'$.chars')),0) FROM model_reasoning WHERE job=?", (job,)).fetchone()[0]
        except sqlite3.Error:
            self.previous_chars = MAX_JOB_TEXT  # Missing observability must not block inference.

    def save(self):
        # Capture errors must never turn a working task into a failed one.
        try:
            with _lock:
                self.record['chars'] = self.chars
                record = json.dumps(self.record)
            with sqlite3.connect(self.studio.db_path, timeout=.1) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA secure_delete=ON')
                job = db.execute('SELECT owner FROM jobs WHERE id=?', (self.job,)).fetchone()
                if not job:return  # Reset/deletion must not recreate orphan records.
                count = db.execute('SELECT count(*) FROM model_reasoning WHERE job=? AND id<>?',
                                   (self.job, self.key)).fetchone()[0]
                if count >= MAX_CALLS:return
                db.execute('INSERT OR REPLACE INTO model_reasoning VALUES (?,?,?,?)',
                           (self.key, self.job, self.record['started'], record))
                # Retain at most the latest 30 missions per account, without enlarging /state.
                db.execute('''DELETE FROM model_reasoning WHERE job IN
                    (SELECT id FROM jobs WHERE owner=? AND id NOT IN
                    (SELECT j.id FROM jobs j JOIN model_reasoning r ON r.job=j.id
                     WHERE j.owner=? GROUP BY j.id ORDER BY j.created DESC LIMIT 30))''',
                           (job['owner'], job['owner']))
        except Exception:
            pass

    def turn(self, model, provider):
        with _lock:
            turn = dict(index=len(self.record['turns']) + 1, model=str(model or '')[:200],
                        provider=provider, status='receiving', sections=[])
            self.current_turn = turn
            if model == 'switchyard':
                if self.live_model and self.live_model.get('routing') and self.live_model.get('model'):
                    self.live_model = {**self.live_model, 'previouslyConfirmed': True}
                else:
                    self.live_model = {'routing': {'strategy': 'switchyard'}}
            else:
                self.live_model = {'model': turn['model']} if turn['model'] else None
            if len(self.record['turns']) < MAX_TURNS:
                self.record['turns'].append(turn)
            else:
                # Keep reporting route headers even after the reasoning transcript is full.
                self.record['truncated'] = True
                turn['modelOnly'] = True
            return turn


def active_model(studio, job, *, observation=None, metrics=None):
    """Show the last confirmed answer model until this agent's next route is known."""
    with _lock:
        for capture in reversed(_active.values()):
            if (capture.job == job and capture.studio.db_path == studio.db_path
                    and (observation is None or capture.record['role'] == observation.get('role'))
                    and capture.record['status'] == 'collecting' and capture.live_model):
                live = dict(role=capture.record['role'], phase=capture.record['phase'], **capture.live_model)
                break
        else:
            return None
    if live.get('model') or not observation:
        return live
    # New phases (including Casey's checks) open a new capture in the same mission.
    agent = observation.get('agent')
    if agent and metrics:
        previous = next((row for row in reversed(metrics.values()) if row.get('agent') == agent), {})
        routing = previous.get('routing') or {}
        if routing.get('strategy') == 'switchyard' and routing.get('model'):
            live.update(model=routing['model'], previouslyConfirmed=True)
    return live


def call(studio, job, role, name, phase, fn, *args, **kwargs):
    capture = Capture(studio, job, role, name, phase)
    with _lock:_active[capture.key] = capture
    token = _current.set(capture)
    try:
        return fn(*args, **kwargs)
    finally:
        _current.reset(token)
        with _lock:
            capture.record['status'] = 'finished'
            for turn in capture.record['turns']:
                if turn['status'] == 'receiving':turn['status'] = 'interrupted'
        capture.save()
        with _lock:
            _active.pop(capture.key, None)


def tag(prompt):
    capture = _current.get()
    return ('[[bac-observe:' + capture.key + ']]\n' + prompt) if capture else prompt


def capturing():
    return _current.get() is not None


def request(payload, provider, *, base_url=''):
    """Remove our transport marker, returning a collector only for an exact live call."""
    if not payload or b'[[bac-observe:' not in payload:return payload, None
    try:value = json.loads(payload)
    except (ValueError, UnicodeError):return payload, None
    if not isinstance(value, dict):return payload, None
    keys = []
    def text(value):
        if not isinstance(value, str):return value
        keys.extend(MARKER.findall(value))
        return MARKER.sub('', value)
    # Only user-message text: never tool arguments, tool results or provider state.
    messages = value.get('messages', value.get('input', []))
    if isinstance(messages, str):value['input'] = text(messages)
    elif isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get('role') != 'user':continue
            content = message.get('content')
            if isinstance(content, str):message['content'] = text(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') in ('text', 'input_text'):
                        part['text'] = text(part.get('text'))
    with _lock:
        # Ambiguous requests are never attached to a guessed job or role.
        captures = {_active[k] for k in keys if k in _active}
        capture = next(iter(captures)) if len(captures) == 1 else None
        turn = capture.turn(value.get('model'), provider) if capture else None
    # Sol verified this adapter format; GPT 6+ variants opt in by user policy.
    # Availability remains model-dependent. Do not change other endpoints.
    model = value.get('model')
    gpt = re.fullmatch(r'(?:azure/openai/|openai/)?gpt-([0-9]+)(?:\.[0-9]+)*(?:-[a-z0-9]+)*', model) if isinstance(model, str) else None
    if (turn is not None and not turn.get('modelOnly') and provider == 'nvidia'
            and gpt is not None and int(gpt.group(1)) >= 6
            and nvidia_endpoints.supported(base_url)):
        options = value.setdefault('reasoning', {})
        if isinstance(options, dict):
            if 'generate_summary' not in options:options.setdefault('summary', 'auto')
            if options.get('summary') or options.get('generate_summary'):
                turn['summaryRequested'] = True
    cleaned = json.dumps(value).encode() if keys else payload
    return cleaned, Collector(capture, turn) if turn else None


class Collector:
    def __init__(self, capture, turn):
        self.capture, self.turn = capture, turn
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.buffer = ''
        self.streaming = False
        self.disabled = bool(turn.get('modelOnly'))
        self.blocks = {}

    def routed_to(self, model, mode):
        with _lock:
            if self.capture.current_turn is self.turn:
                self.capture.live_model = {'model': model, 'routing': {'strategy': 'switchyard', 'mode': mode}}

    def section(self, key, text, kind='text', delta=False):
        if not isinstance(text, str) or not text:return
        with _lock:
            section = self.blocks.get(key)
            if section is None:
                if len(self.blocks) >= 16:return
                section = dict(kind=kind, text='')
                self.blocks[key] = section
                self.turn['sections'].append(section)
            # Completed/snapshot events replace their delta stream; never append it twice.
            previous = section['text']
            candidate = previous + text if delta else text
            budget = min(MAX_TEXT, len(previous) + max(0, MAX_JOB_TEXT - self.capture.previous_chars - self.capture.chars))
            section['text'] = candidate[:budget]
            self.capture.chars += len(section['text']) - len(previous)
            if len(candidate) > budget:section['truncated'] = self.capture.record['truncated'] = True

    def item(self, item, prefix):
        if not isinstance(item, dict) or item.get('type') != 'reasoning':return
        for index, part in enumerate(item.get('summary', []) or []):
            if isinstance(part, dict) and part.get('type') == 'summary_text':
                self.section((prefix, 'summary', index), part.get('text'), 'summary')
        for index, part in enumerate(item.get('content', []) or []):
            if isinstance(part, dict) and part.get('type') == 'reasoning_text':
                self.section((prefix, 'text', index), part.get('text'))

    def event(self, value):
        if not isinstance(value, dict):return
        if isinstance(value.get('model'), str):self.turn['model'] = value['model'][:200]
        for choice in value.get('choices', []) or []:
            if not isinstance(choice, dict) or choice.get('index', 0) != 0:continue
            delta = 'delta' in choice
            message = choice.get('delta') if delta else choice.get('message')
            if not isinstance(message, dict):continue
            for field in ('reasoning_content', 'reasoning', 'reasoning_text'):
                if isinstance(message.get(field), str):
                    self.section(('chat', field), message[field],
                                 'summary' if self.turn.get('summaryRequested') else 'text', delta=delta)
                    break  # Aliases are not independent copies of the same text.
            details=message.get('reasoning_details', []) or []
            for part in details if isinstance(details, list) else []:
                if not isinstance(part, dict):continue
                typ = part.get('type')
                if typ in ('reasoning.text', 'reasoning.summary'):
                    self.section(('details', part.get('index', 0)), part.get('text', part.get('summary')),
                                 'summary' if typ.endswith('summary') else 'text', delta)
            # Some OpenAI-compatible gateways wrap Responses items in a chat
            # message. Read public summaries only; encrypted_content stays opaque.
            items = message.get('reasoning_items', [])
            for index, item in enumerate(items if isinstance(items, list) else []):
                if isinstance(item, dict):self.item(item, ('chat-item', item.get('id', index)))
            self.deduplicate_chat_summary()
        typ = value.get('type', '')
        for field, kind in [('reasoning_summary_text', 'summary'), ('reasoning_text', 'text')]:
            if typ in ('response.'+field+'.delta', 'response.'+field+'.done'):
                self.section((value.get('item_id', value.get('output_index', 0)), kind,
                              value.get('summary_index', value.get('content_index', 0))),
                             value.get('delta', value.get('text')), kind, typ.endswith('.delta'))
        if typ == 'response.output_item.done':
            item = value.get('item', {})
            self.item(item, item.get('id', value.get('output_index', 0)))
        response = value.get('response', value)
        if isinstance(response, dict):
            for index, item in enumerate(response.get('output', []) or []):
                if isinstance(item, dict):self.item(item, item.get('id', index))
        # Anthropic publishes thinking blocks separately; signatures/redacted blocks are opaque.
        block = value.get('content_block', {})
        if typ == 'content_block_start' and block.get('type') == 'thinking':
            self.section(('anthropic', value.get('index', 0)), block.get('thinking'))
        delta = value.get('delta', {})
        if typ == 'content_block_delta' and delta.get('type') == 'thinking_delta':
            self.section(('anthropic', value.get('index', 0)), delta.get('thinking'), delta=True)
        if value.get('type') == 'message':
            for index, block in enumerate(value.get('content', []) or []):
                if isinstance(block, dict) and block.get('type') == 'thinking':
                    self.section(('anthropic', index), block.get('thinking'))

    def deduplicate_chat_summary(self):
        # Some adapters publish the same summary as both a flat chat field and
        # structured Responses items. Prefer the labelled items only on a full
        # text match; distinct public text and separate reasoning items survive.
        with _lock:
            summaries = [section for key, section in self.blocks.items()
                         if isinstance(key[0], tuple) and key[0][0] == 'chat-item'
                         and key[1] == 'summary' and section['text']]
            if not summaries or any(s.get('truncated') for s in summaries):return
            normalized = lambda text: ' '.join(text.split())
            combined = normalized(' '.join(s['text'] for s in summaries))
            for key, section in list(self.blocks.items()):
                if (key[0] == 'chat' and not section.get('truncated')
                        and normalized(section['text']) == combined):
                    self.turn['sections'] = [s for s in self.turn['sections'] if s is not section]
                    self.capture.chars -= len(section['text'])
                    del self.blocks[key]

    def feed(self, chunk):
        if self.disabled:return
        try:
            self.buffer += self.decoder.decode(chunk)
            if len(self.buffer) > 512000:
                self.disabled = True
                self.capture.record['truncated'] = True
                self.buffer = ''
                return
            if self.streaming:
                self.buffer = self.buffer.replace('\r\n', '\n')
                while '\n\n' in self.buffer:
                    event, self.buffer = self.buffer.split('\n\n', 1)
                    data = '\n'.join(line[5:].lstrip() for line in event.split('\n') if line.startswith('data:'))
                    if data and data != '[DONE]':
                        try:self.event(json.loads(data))
                        except (ValueError, TypeError, AttributeError):pass
        except Exception:
            self.disabled = True  # Observability is never required for delivery.

    def finish(self, complete=True):
        if self.turn.get('modelOnly'):return
        try:
            if not self.streaming and not self.disabled and self.buffer:self.event(json.loads(self.buffer))
        except (ValueError, TypeError, AttributeError):pass
        with _lock:
            self.turn['status'] = 'complete' if complete else 'interrupted'
        self.capture.save()
        self.buffer = ''


def report(studio, owner, job):
    from studio import Problem
    with studio.db() as db:
        row = db.execute('SELECT status FROM jobs WHERE id=? AND owner=?', (job, owner)).fetchone()
        if not row:raise Problem('Mission not found.', 404)
        records = {r['id']:json.loads(r['record']) for r in db.execute(
            'SELECT id,record FROM model_reasoning WHERE job=? ORDER BY started LIMIT ?', (job, MAX_CALLS))}
    with _lock:
        for capture in _active.values():
            if capture.job == job and capture.studio.db_path == studio.db_path:
                records[capture.key] = copy.deepcopy(capture.record)
    calls = sorted(records.values(), key=lambda item:item['started'])[:MAX_CALLS]
    return dict(job=job, calls=calls, active=row['status'] in ('queued', 'running', 'stopping'),
                recorded=bool(calls), truncated=any(c.get('truncated') for c in calls))
