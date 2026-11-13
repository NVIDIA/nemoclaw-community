#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Ask a host-side NVIDIA Auto Ontology deployment a grounded question about the provider_billing database. Standard library only.

  python3 utilities/ontology_qa.py --question "..." [--output FILE]

Auto Ontology is a semantic layer over the provider-billing database: it knows the tables, keys and measures, turns the
question into SQL, runs it and returns the SQL, the rows and an answer. This script checks the semantic layer is compiled
(GET /api/semantic-compilation/status), asks how well the layer covers the question (POST /api/question-entity-coverage),
then asks it (POST /api/chat/completions, a Server-Sent Events stream) and prints the generated SQL, the rows and the answer.

  AUTO_ONTOLOGY_API_URL    default http://host.openshell.internal:4000 (the deployment's web origin, reached from a sandbox)
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
import urllib.error
import urllib.request
from pathlib import Path

TARGET_DB = 'provider_billing'
BASE = os.environ.get('AUTO_ONTOLOGY_API_URL', 'http://host.openshell.internal:4000')
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


def read_events(response):
    events = []
    for raw in response:
        line = raw.decode('utf-8', 'replace').strip()
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            break
        try:
            events.append(json.loads(payload))
        except ValueError:
            events.append({'unparsed': payload})
    return events


def ask(question):
    status = json.load(request('GET', '/api/semantic-compilation/status', timeout=60))
    if not status.get('calculated') or status.get('running'):
        raise RuntimeError(f'semantic layer not ready: {status}')
    coverage = json.load(request('POST', '/api/question-entity-coverage', {'question': question}, timeout=120))
    with request('POST', '/api/chat/completions', {'question': question, 'target_db': TARGET_DB}) as response:
        events = read_events(response)
    return {'compilation_status': status, 'coverage': coverage, 'events': events}


def summarize(events):
    """The generated SQL, the rows it returned and the answer text, from the stream's final result event."""
    result = next((e for e in events if e.get('type') == 'result'), None)
    answer = result.get('answer') if result else None
    if isinstance(answer, str):
        try:
            answer = ast.literal_eval(answer)
        except (ValueError, SyntaxError):
            answer = {'response': answer}
    answer = answer if isinstance(answer, dict) else {}
    rows = None
    raw = answer.get('sql_response_from_db') or []
    try:
        rows = json.loads(raw[0]) if raw else []
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
    except (RuntimeError, urllib.error.URLError, OSError, ValueError) as exc:
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
             'check': 'Read the SQL and verify it against the data (for example with integrity_tool.py) before relying on it.'}
    print(json.dumps(shown, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
