#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Ask a host-side NVIDIA Auto Ontology deployment a grounded question about the market database. Standard library only.

  python3 utilities/ontology_qa.py --question "..." [--output FILE]

Auto Ontology is a semantic layer over the market-analysis database: it knows the tables, keys and measures, turns the
question into SQL, runs it and returns the SQL, the rows and an answer. This script checks the semantic layer is compiled
(GET /api/semantic-compilation/status), asks how well the layer covers the question (POST /api/question-entity-coverage),
then asks it (POST /api/chat/completions, a Server-Sent Events stream) and prints the generated SQL, the rows and the answer.

  AUTO_ONTOLOGY_API_URL    the deployment's web origin as seen from the sandbox. When unset, the first line of ontology.url next
                           to this script (written by scripts/install.sh from AUTO_ONTOLOGY_PORT), else
                           http://host.openshell.internal:4000
  AUTO_ONTOLOGY_API_TOKEN  the x-api-key token. In a sandbox this is a placeholder that the egress proxy replaces on the way to
                           the bound host; the real token is never in the sandbox.
  AUTO_ONTOLOGY_TIMEOUT_SECONDS  per-request timeout for the chat stream, default 900 (a reasoning model can take minutes)

THE ANSWER IS A PROPOSAL, NOT A FACT. The generated SQL can be wrong in ways the answer text hides (a wrong denominator, a
missing as-of date, a question it should have declined). Read the SQL and check it against the data before relying on it.
A failed or unreachable call exits 1 with "blocked" and nothing is substituted.
"""
import argparse
import ast
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TARGET_DB = 'market'


def base_url():
    if os.environ.get('AUTO_ONTOLOGY_API_URL'):
        return os.environ['AUTO_ONTOLOGY_API_URL']
    try:
        return (Path(__file__).with_name('ontology.url').read_text().strip().splitlines() or [''])[0] or DEFAULT_URL
    except OSError:
        return DEFAULT_URL


DEFAULT_URL = 'http://host.openshell.internal:4000'
BASE = base_url()
ROW_LIMIT = 50


def request(method, path, body=None, timeout=None):
    token = os.environ.get('AUTO_ONTOLOGY_API_TOKEN')
    if not token:
        raise RuntimeError('AUTO_ONTOLOGY_API_TOKEN is not set (re-run scripts/install.sh with the token in .env, then '
                           'restart the sandbox: nemoclaw <name> stop, then start)')
    timeout = timeout or int(os.environ.get('AUTO_ONTOLOGY_TIMEOUT_SECONDS', '900'))
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE.rstrip('/') + path, data=data, method=method,
                                 headers={'x-api-key': token, 'Content-Type': 'application/json',
                                          'Accept': 'application/json, text/event-stream'})
    return urllib.request.urlopen(req, timeout=timeout)


def read_events(response, deadline):
    """Server-Sent Events: a blank line ends an event, and a data field may span several `data:` lines.
    `deadline` is a total time limit (time.monotonic()); the socket timeout alone resets on every read."""
    events, data = [], []

    def flush():
        if not data:
            return False
        payload = '\n'.join(data).strip()
        data.clear()
        if payload == '[DONE]':
            return True
        try:
            events.append(json.loads(payload))
        except ValueError:
            events.append({'unparsed': payload})
        return False

    for raw in response:
        if time.monotonic() > deadline:
            raise TimeoutError('the chat stream did not finish before the total deadline')
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if not line.strip():
            if flush():
                return events
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
    flush()
    return events


def ask(question):
    status = json.load(request('GET', '/api/semantic-compilation/status', timeout=60))
    if not status.get('calculated') or status.get('running'):
        raise RuntimeError(f'semantic layer not ready: {status}')
    coverage = json.load(request('POST', '/api/question-entity-coverage', {'question': question}, timeout=120))
    deadline = time.monotonic() + int(os.environ.get('AUTO_ONTOLOGY_TIMEOUT_SECONDS', '900'))
    with request('POST', '/api/chat/completions', {'question': question, 'target_db': TARGET_DB}) as response:
        events = read_events(response, deadline)
    errors = [e for e in events if e.get('type') == 'error']
    if errors:
        raise RuntimeError(f'the service reported an error: {json.dumps(errors[0], default=str)[:300]}')
    if not any(e.get('type') == 'result' for e in events):
        raise RuntimeError(f'the stream ended without a result event ({len(events)} events); it may have been cut off')
    return {'compilation_status': status, 'coverage': coverage, 'events': events}


def summarize(events):
    """The generated SQL, the rows it returned and the answer text, from the stream's final result event."""
    result = next((e for e in events if e.get('type') == 'result'), None)
    answer = result.get('answer') if result else None
    if isinstance(answer, str):
        try:
            answer = ast.literal_eval(answer)
        except (ValueError, SyntaxError, RecursionError, MemoryError):
            answer = {'response': answer}
    answer = answer if isinstance(answer, dict) else {}
    # rows is None when no SQL result came back, so "no answer" is never mistaken for "the SQL returned zero rows"
    rows = None
    raw = answer.get('sql_response_from_db')
    try:
        parsed = json.loads(raw[0]) if raw else None
        rows = parsed if isinstance(parsed, list) else None
    except (ValueError, TypeError, IndexError):
        rows = None
    return {'sql': answer.get('sql_code'), 'rows': rows, 'response': answer.get('response'), 'answered_with_sql': bool(answer.get('sql_code'))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--question', required=True, help='a business question; state the as-of date in it')
    ap.add_argument('--output', type=Path, help='write the full receipt (every stream event) here')
    args = ap.parse_args()
    try:
        result = ask(args.question)
    except Exception as exc:  # any failure is a blocked answer, never a traceback or a partial success
        ap.exit(1, f'blocked: Auto Ontology answer not obtained ({type(exc).__name__}: {exc}); nothing was substituted. '
                   'Report the ontology answer as blocked.\n')
    summary = summarize(result['events'])
    receipt = {'tool': 'auto_ontology', 'api_url': BASE, 'target_db': TARGET_DB, 'question': args.question, **result}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    rows = summary['rows']
    shown = {'tool': 'auto_ontology', 'target_db': TARGET_DB, 'question': args.question,
             'coverage': result['coverage'], 'sql': summary['sql'], 'answered_with_sql': summary['answered_with_sql'],
             'row_count': None if rows is None else len(rows),
             'rows': None if rows is None else rows[:ROW_LIMIT],
             'response': summary['response'], 'events': len(result['events']),
             'check': 'Read the SQL and verify it against the data (for example with a short script over data/) before relying on it.'}
    if summary['answered_with_sql']:
        shown['trace_markdown'] = ('**Auto Ontology SQL** (database `%s`, %s rows returned)\n\n```sql\n%s\n```'
                                   % (TARGET_DB, shown['row_count'], summary['sql'].strip()))
    else:
        shown['trace_markdown'] = '**Auto Ontology SQL:** none. It returned: %s' % (summary['response'] or 'no message')
    if not summary['answered_with_sql']:
        shown['note'] = 'Auto Ontology returned no SQL for this question; treat the ontology answer as blocked.'
        print('note: Auto Ontology returned no SQL; treat the ontology answer as blocked. Nothing was substituted.', file=sys.stderr)
    print(json.dumps(shown, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
