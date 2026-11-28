# SPDX-License-Identifier: Apache-2.0

"""Observed run usage and host utilization; never inferred token counts."""
import json
import math
import platform
import re
import secrets
import sqlite3
from contextlib import closing
import subprocess
import threading
import time
from pathlib import Path

class Reply(str):
    def __new__(cls, text, metrics):
        value = super().__new__(cls, text)
        value.metrics = metrics
        return value


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def context_usage(state_dir, agent, session, started, measured_at=None):
    """Read this run's native session counters, never its aggregate API usage."""
    context = limit = model = None
    try:
        root = Path(state_dir) / 'agents' / agent
        database = root / 'agent/openclaw-agent.sqlite'
        key = 'agent:' + agent + ':openai-user:' + session
        if database.is_file():
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
                row = db.execute('SELECT entry_json FROM session_nodes WHERE session_key=?', (key,)).fetchone()
            entry = json.loads(row[0]) if row else {}
        else:
            entries = json.loads((root / 'sessions/sessions.json').read_text())
            entry = entries.get(key, {})
        updated = number(entry.get('updatedAt'))
        if (updated is not None and updated >= started * 1000
                and (measured_at is None or updated <= measured_at * 1000)
                and entry.get('totalTokensFresh') is True and entry.get('totalTokensVersion') == 1):
            context = number(entry.get('totalTokens'))
            limit = number(entry.get('contextTokens'))
            model = entry.get('model')
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error):
        pass
    return {'context': context, 'limit': limit, 'model': model}


def measure(result, state_dir, agent, session, started, elapsed=None):
    usage = result.get('usage') or {}
    tokens = {key: number(usage.get(source)) for key, source in [('input','prompt_tokens'),('output','completion_tokens'),('total','total_tokens')]}
    # Gateway can return an all-zero placeholder when the provider reports nothing.
    if not any(value for value in tokens.values()):
        tokens = dict.fromkeys(tokens)
    duration = number(elapsed)
    if duration == 0:
        duration = None
    speed = tokens['output'] / duration if duration is not None and tokens['output'] is not None else None
    observed = context_usage(state_dir, agent, session, started)
    # The Gateway can return its HTTP response just before the native session
    # transaction becomes readable. Briefly retry the exact agent/session so a
    # successful turn is not permanently recorded without its context snapshot.
    for _ in range(3):
        if observed['context'] is not None:
            break
        time.sleep(.05)
        observed = context_usage(state_dir, agent, session, started)
    return {**tokens, **observed,
            'runSeconds': duration, 'outputTokensPerSecond': speed,
            'session': session, 'measuredAt': time.time(), 'turnId': secrets.token_hex(12)}

_lock = threading.Lock()
_cached = {'cpu': None, 'memory': None, 'sampledAt': 0}
_previous = None


def host():
    global _cached, _previous
    with _lock:
        if time.time() - _cached['sampledAt'] < 8:
            return dict(_cached)
        cpu = memory = None
        try:
            if platform.system() == 'Linux':
                values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
                current = (sum(values), values[3] + values[4])
                if _previous and current[0] > _previous[0]:
                    cpu = 100 * (1 - (current[1] - _previous[1]) / (current[0] - _previous[0]))
                _previous = current
                mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
                memory = 100 * (1 - mem['MemAvailable'] / mem['MemTotal'])
            elif platform.system() == 'Darwin':
                # One host snapshot. top's CPU is system-wide, not this Python process.
                out = subprocess.run(['/usr/bin/top','-l','2','-s','1','-n','0'], capture_output=True, text=True, timeout=4).stdout
                matches = re.findall(r'CPU usage:.*?([\d.]+)% idle', out)
                if len(matches) > 1: cpu = 100 - float(matches[-1])
                vm = subprocess.run(['/usr/bin/vm_stat'], capture_output=True, text=True, timeout=2).stdout
                page = int(re.search(r'page size of (\d+)', vm)[1])
                counts = {k: int(v) for k,v in re.findall(r'^([^:\n]+):\s+(\d+)\.', vm, re.M)}
                total = int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize'], text=True, timeout=2))
                # Physical footprint: active + wired + compressor pages; exclude reclaimable inactive cache.
                memory = 100 * page * sum(counts[k] for k in ['Pages active','Pages wired down','Pages occupied by compressor']) / total
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass
        _cached = {'cpu': None if cpu is None else round(max(0,min(100,cpu)),1), 'memory': None if memory is None else round(max(0,min(100,memory)),1), 'sampledAt': time.time()}
        return dict(_cached)


def report(studio, owner):
    agents = {}
    sources = {}
    total = 0
    measured = missing = 0
    with studio.db() as db:
        # Histories can contain large research/handoff payloads. Read only measured
        # usage instead of decoding every saved task body on each meter refresh.
        rows = db.execute("SELECT id,owner,created,json_extract(payload,'$.preset') AS preset,json_extract(payload,'$.metrics') AS metrics,kind FROM jobs WHERE owner IN (SELECT id FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?)) AND json_type(payload,'$.metrics')='object' ORDER BY created", (owner,))
        for row in rows:
            for stage, record in json.loads(row['metrics']).items():
                stage = record.get('stage', stage)
                crew = row['kind'] in ('crew', 'crew-chat')
                key = (record['agent'], crew)
                previous = agents.get(key, {'total':0, 'calls':0})
                amount = number(record.get('total'))
                if amount is None: missing += 1
                else: total += amount; measured += 1
                newer = (number(record.get('measuredAt')) is None or number(previous.get('measuredAt')) is None
                         or record['measuredAt'] >= previous['measuredAt'])
                agents[key] = {**(record if newer else previous), 'total': previous['total'] + (amount or 0), 'calls': previous['calls'] + (amount is not None), 'crew': crew}
                session = record.get('session')
                if not session and row['kind'] == 'crew':
                    session = 'bac-' + row['owner'] if stage == '0' and not row['preset'] else 'bac-crew-' + row['id'] + '-' + stage
                elif not session and row['kind'] == 'chat':
                    session = 'bac-' + row['owner']
                if newer:sources[key] = (session, row['created'])
    # Repair display of previously recorded runs without rewriting history or
    # attributing a newer session's context to an older run.
    from agent_runtime import root
    for key, record in agents.items():
        session, started = sources[key]
        measured_at = number(record.get('measuredAt'))
        if session and measured_at is not None and (record.get('context') is None or record.get('limit') is None):
            # A delayed commit from this turn may become readable later, but its
            # native timestamp cannot be newer than the recorded response.
            # Reject later turns that reused the same session.
            observed = context_usage(root() / 'state', key[0], session, started, measured_at)
            if observed['context'] is not None:
                record.update(observed)
    return {'host':host(), 'agents':list(agents.values()), 'total':total if measured else None, 'measuredCalls':measured, 'unreportedCalls':missing}
