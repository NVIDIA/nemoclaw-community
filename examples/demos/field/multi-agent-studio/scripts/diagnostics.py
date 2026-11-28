# SPDX-License-Identifier: Apache-2.0

"""Bounded, content-free support records. Never ingest raw logs or request bodies."""
from collections import deque
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import traceback

REQUEST = ContextVar('diagnostic_request', default={})
ROOT = Path(__file__).resolve().parents[1]
ROUTES = frozenset(('session state runtime diagnostics telemetry settings settings/models settings/start '
    'settings/team-model settings/connections settings/connections/preferences settings/connections/check '
    'settings/connections/models settings/scenario-model settings/scenario-models credential-session '
    'agents onboard profile agent-model delete-agent agent-policy crew-policy jobs upload decision '
    'retry-reaction reset crew-chat-reset bac-reset heartbeat team-model '
    'file workspace-files agent-documents evidence security').split())
STATES = {'queued', 'running', 'waiting', 'stopping', 'done', 'error', 'cancelled'}


def route_name(path):
    name = path.split('?', 1)[0].removeprefix('/api/')
    return name if name in ROUTES else 'unknown'


def ref(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{12,32}', value) else None


def number(value):
    return round(value, 3) if type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1e12 else None


def model_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w./:-]{1,160}', value):return None
    if re.search(r'(?i)(sk-|nvapi-|hf_|api.?key|token|secret|https?:)', value):return None
    return value


def cause(value):
    """Categorize for triage; never retain the input or infer OpenShell from HTTP 403."""
    value = str(value).lower()
    if 'parameter' in value and 'unsupported' in value:return 'tool-arguments'
    for code, terms in (
        ('context-limit', ('context limit', 'context length', 'context window', 'maximum context')),
        ('rate-limit', ('rate limit', 'quota', '429')),
        ('timeout', ('timed out', 'timeout', 'took too long')),
        ('missing-handoff', ('required handoff', 'incomplete handoff', 'no saved update')),
        ('out-of-scope', ('out of scope', 'out-of-scope', 'required expertise unavailable')),
        ('model-unavailable', ('model not found', 'model unavailable')),
        ('authentication', ('unauthorized', 'invalid api key', 'authentication', '401')),
        ('connection', ('connection refused', 'connection error', 'unreachable', 'gateway unavailable')),
    ):
        if any(term in value for term in terms):return code
    if 'openshell' in value and any(word in value for word in ('blocked', 'denied', 'deny')):return 'reported-openshell-denial'
    if any(word in value for word in ('forbidden', 'permission denied', '403')):return 'access-denied'
    return 'unclassified'


def phase(title):
    value = str(title).lower()
    for name, words in (('cancel', ('cancel', 'stop')), ('repair', ('repair', 'retry')),
                        ('review', ('review', 'check')), ('artifact', ('file', 'handoff', 'deliver', 'saved')),
                        ('planning', ('plan', 'assign')), ('research', ('search', 'research', 'fetch')),
                        ('preparation', ('prepar', 'connect')), ('completion', ('complete', 'done'))):
        if any(word in value for word in words):return name
    return 'progress'


def exception_info(error):
    # Frame locations only: exception messages, source lines and locals may contain secrets.
    frames = []
    for frame in traceback.extract_tb(error.__traceback__)[-8:]:
        path = Path(frame.filename)
        try: filename = str(path.resolve().relative_to(ROOT))
        except (ValueError, OSError): filename = 'external'
        frames.append({'file': filename, 'line': frame.lineno, 'function': frame.name if filename != 'external' else 'external'})
    return {'type': type(error).__name__, 'category': cause(error), 'frames': frames}


class Diagnostics:
    MAX_BYTES = 1_000_000
    BACKUPS = 3

    def __init__(self, directory):
        self.path = Path(directory) / 'logs' / 'diagnostics.jsonl'
        self.lock = threading.RLock()
        self.recent = deque(maxlen=1200)
        self.available = True
        self.run = secrets.token_hex(8)
        self.started = time.time()
        self.runtime = {}
        self.runtime_at = None
        try: self.build = json.loads((ROOT / 'app/version.json').read_text())
        except (OSError, ValueError): self.build = {'version': 'unversioned'}
        try: self.fingerprint = hashlib.sha256((ROOT / 'app/index.html').read_bytes()).hexdigest()[:16]
        except OSError: self.fingerprint = 'unavailable'
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for index in range(self.BACKUPS, -1, -1):
                path = self.file(index)
                if not path.is_file():continue
                with path.open('rb') as source:
                    source.seek(max(0, path.stat().st_size-self.MAX_BYTES))
                    for line in source:
                        try: row = json.loads(line)
                        except ValueError: continue
                        if isinstance(row, dict) and row.get('schema') == 1:self.recent.append(row)
        except OSError:self.available = False
        self.emit('server.started')

    def file(self, index):
        return self.path if index == 0 else Path(str(self.path)+'.'+str(index))

    def emit(self, event, *, participant=None, error=None, **fields):
        context = REQUEST.get()
        row = {'schema': 1, 'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
               'event': event, 'run': self.run, 'version': self.build.get('version'),
               'commit': self.build.get('commit'), 'build': self.fingerprint}
        participant = participant or context.get('participant')
        if ref(participant):row['participant'] = participant
        if ref(context.get('requestId')):row['requestId'] = context['requestId']
        # Only internal, explicitly selected metadata reaches the file.
        for key in ('job', 'agent', 'requestId'):
            if ref(fields.get(key)):row[key] = fields[key]
        for key in ('elapsedMs', 'statusCode', 'role', 'inputTokens', 'outputTokens', 'modelMs'):
            if number(fields.get(key)) is not None:row[key] = number(fields[key])
        if fields.get('status') in STATES:row['status'] = fields['status']
        if fields.get('method') in ('GET', 'POST'):row['method'] = fields['method']
        if 'route' in fields:row['route'] = route_name(fields['route'])
        if 'phase' in fields:row['phase'] = phase(fields['phase'])
        if 'hint' in fields:row['category'] = cause(fields['hint'])
        if fields.get('outcome') in ('partial','complete','unavailable','done'):row['outcome'] = fields['outcome']
        if fields.get('teamMode') in ('hired','mixed','builtin'):row['teamMode'] = fields['teamMode']
        if fields.get('runtimeChanged'):row['runtime'] = self.runtime
        if 'model' in fields and model_name(fields['model']):row['model'] = model_name(fields['model'])
        if error is not None:row['error'] = exception_info(error)
        with self.lock:
            self.recent.append(row)
            try:
                encoded = (json.dumps(row, ensure_ascii=True, separators=(',', ':'))+'\n').encode()
                if self.path.exists() and self.path.stat().st_size+len(encoded)>self.MAX_BYTES:
                    self.file(self.BACKUPS).unlink(missing_ok=True)
                    for index in range(self.BACKUPS-1, -1, -1):
                        if self.file(index).exists():self.file(index).replace(self.file(index+1))
                fd = os.open(self.path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
                with os.fdopen(fd, 'ab') as target:
                    os.chmod(self.path, 0o600)
                    target.write(encoded)
                self.available = True
            except OSError:self.available = False  # Diagnostics must not break a demo.

    def observe_runtime(self, runtime):
        state = {key: runtime[key] for key in ('ready', 'gateway', 'model', 'teamReady', 'teamModel')
                 if type(runtime.get(key)) is bool}
        for key in ('gatewayState', 'gatewayProbe'):
            if runtime.get(key) in ('ready', 'slow', 'unavailable', 'ok', 'timeout', 'refused', 'error'):
                state[key] = runtime[key]
        state['connections'] = {}
        warmup = runtime.get('openshellWarmup', {})
        if warmup.get('state') in ('checking', 'preparing', 'cleaning', 'ready', 'unavailable', 'not-configured', 'skipped', 'cancelled'):
            state['openshellWarmup'] = {'state': warmup['state']}
            if number(warmup.get('elapsedMs')) is not None:state['openshellWarmup']['elapsedMs'] = number(warmup['elapsedMs'])
        for key in ('local', 'api'):
            value = runtime.get('modelConnections', {}).get('connections', {}).get(key, {})
            state['connections'][key] = {k: value[k] for k in ('ready', 'enabled') if type(value.get(k)) is bool}
            if model_name(value.get('model')):state['connections'][key]['model'] = model_name(value['model'])
        with self.lock:
            changed = state != self.runtime
            self.runtime, self.runtime_at = state, time.time()
        if changed:self.emit('runtime.changed', runtimeChanged=True)

    @staticmethod
    @contextmanager
    def database(studio):
        # Use the same read/write locking mode as queue connections. Mixing
        # read-only and writable handles can produce SQLITE_IOERR in macOS's
        # bundled SQLite under concurrent writes. query_only still prevents
        # diagnostic queries from changing data; mode=rw never creates a DB.
        db = sqlite3.connect(Path(studio.db_path).resolve().as_uri()+'?mode=rw', uri=True, timeout=.15)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            yield db
        finally:db.close()

    def job(self, studio, job_id, event, **fields):
        # This read runs after the job transaction commits, never under its write lock.
        try:
            with self.database(studio) as db:
                job = db.execute('SELECT j.status,j.owner,j.created,j.payload,a.participant FROM jobs j '
                                 'LEFT JOIN agents a ON j.owner=a.id WHERE j.id=?', (job_id,)).fetchone()
            if job:
                payload = json.loads(job['payload'])
                fields.update(teamMode=payload.get('teamMode'), outcome=(payload.get('collaboration') or {}).get('outcome'))
                self.emit(event, participant=job['participant'], job=job_id, agent=job['owner'],
                          status=job['status'], elapsedMs=max(0, time.time()-job['created'])*1000, **fields)
        except Exception:
            # A busy/deleted database must not alter task execution.
            self.emit('diagnostics.job-unavailable')

    def agent_event(self, studio, owner, event, **fields):
        try:
            with self.database(studio) as db:
                row = db.execute('SELECT participant FROM agents WHERE id=?', (owner,)).fetchone()
            if row:self.emit(event, participant=row['participant'], agent=owner, **fields)
        except Exception:pass

    def workload(self, studio, participant):
        if studio is None:return None
        try:
            with self.database(studio) as db:
                rows = db.execute('SELECT j.id,j.status,j.kind,j.created,j.updated FROM jobs j '
                    'JOIN agents a ON j.owner=a.id WHERE a.participant=? ORDER BY j.updated DESC LIMIT 12',
                    (participant,)).fetchall()
                counts = db.execute('SELECT j.status,count(*) FROM jobs j JOIN agents a ON j.owner=a.id '
                    'WHERE a.participant=? GROUP BY j.status', (participant,)).fetchall()
                hires = db.execute("SELECT count(*) FROM agents WHERE participant=? AND kind='personal' "
                    "AND profile IS NOT NULL AND deleting=0", (participant,)).fetchone()[0]
            return {'hiredAgents': hires, 'jobCounts': {r[0]:r[1] for r in counts if r[0] in STATES},
                    'recentJobs': [{'job': r['id'], 'status': r['status'],
                       'createdAt': r['created'], 'updatedAt': r['updated']} for r in rows if r['status'] in STATES]}
        except Exception:return {'available': False}

    def report(self, participant, full=False, studio=None):
        workload = self.workload(studio,participant)
        with self.lock:
            rows = [r for r in self.recent if r.get('participant') == participant or
                    (not r.get('participant') and r.get('event') in ('server.started', 'runtime.changed', 'openshell.warmup'))]
            limit, budget = (400, 200_000) if full else (80, 48_000)
            chosen = []
            for row in reversed(rows[-limit:]):
                clean = {k: v for k, v in row.items() if k != 'participant'}
                size = len(json.dumps(clean).encode())
                if size > budget:break
                chosen.append(clean);budget -= size
            return {'schema': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
                    'serverBuild': self.build, 'buildFingerprint': self.fingerprint, 'run': self.run,
                    'serverEnvironment': {'os':platform.system(), 'python':platform.python_version()},
                    'workload': workload,
                    'uptimeSeconds': round(time.time()-self.started), 'storage': 'file' if self.available else 'memory-only',
                    'runtime': self.runtime, 'runtimeObservedAt': self.runtime_at,
                    'events': list(reversed(chosen)), 'eventsOmitted': max(0, len(rows)-len(chosen)),
                    'privacy': 'No prompts, responses, file contents, credentials, URLs or raw runtime logs.'}


def traced_request(method):
    @wraps(method)
    def wrapped(handler):
        if not handler.path.startswith('/api/'):
            return method(handler)
        handler._diag_status = 500
        handler._diag_error = None
        handler._diag_request = secrets.token_hex(8)
        token = REQUEST.set({'requestId': handler._diag_request})
        started = time.monotonic()
        try:
            return method(handler)
        except (BrokenPipeError, ConnectionResetError):
            handler._diag_status = 499
        except Exception as error:
            handler._diag_error = error
            try: handler.json_response({'error': 'The host could not complete the request. Copy diagnostics in Settings > Reset > Issue report.',
                                        'requestId': handler._diag_request}, 500)
            except (BrokenPipeError, ConnectionResetError):pass
        finally:
            elapsed = (time.monotonic()-started)*1000
            route = route_name(handler.path)
            if handler._diag_status >= 400 or elapsed > 1500 or (handler.command == 'POST' and route != 'credential-session'):
                handler.server.studio.diagnostics.emit('request.finished', route=route, method=handler.command,
                    statusCode=handler._diag_status, elapsedMs=elapsed, error=handler._diag_error)
            REQUEST.reset(token)
            handler._diag_request = None
            handler._diag_error = None
    return wrapped
