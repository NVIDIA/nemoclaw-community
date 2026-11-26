#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline test of ontology_qa.py against a local fake Auto Ontology server. No network, no real token.

  python3 scripts/tests/test_ontology_qa.py

Covers the success path (multi-line SSE data included) and the cases that must be reported as blocked:
a stream cut off before the result event, an error event, and a failed status call.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / 'skills' / 'market-analysis' / 'utilities' / 'ontology_qa.py'
ANSWER = {'sql_code': "SELECT asset_id FROM assets WHERE sector = 'Manufacturing'",
          'sql_response_from_db': [json.dumps([{'asset_id': 'STIO'}, {'asset_id': 'TISL'}])], 'response': 'ok'}
MODES = {
    'success': ['data: {"type": "progress"}\n\n',
                'data: {"type": "result",\ndata: "answer": ' + json.dumps(json.dumps(ANSWER)) + '}\n\n', 'data: [DONE]\n\n'],
    'sql-no-rows': ['data: {"type": "result",\ndata: "answer": ' + json.dumps(json.dumps({'sql_code': ANSWER['sql_code'], 'response': 'ok'})) + '}\n\n'],
    'sql-empty': ['data: {"type": "result",\ndata: "answer": ' + json.dumps(json.dumps({**ANSWER, 'sql_response_from_db': ['[]']})) + '}\n\n'],
    'sql-bad-rows': ['data: {"type": "result",\ndata: "answer": ' + json.dumps(json.dumps({**ANSWER, 'sql_response_from_db': ['not json']})) + '}\n\n'],
    'cut': ['data: {"type": "progress"}\n\n'],
    'error': ['data: {"type": "error", "message": "model timeout"}\n\n'],
}


class Handler(BaseHTTPRequestHandler):
    mode = 'success'

    def log_message(self, *args):
        pass

    def reply(self, code, body, kind='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.headers.get('x-api-key') != 'fake-token' or Handler.mode == 'status-fail':
            return self.reply(500, '{}')
        self.reply(200, json.dumps({'calculated': True, 'running': False}))

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path.endswith('question-entity-coverage'):
            return self.reply(200, json.dumps({'data': {'coverage': 1.0}}))
        self.reply(200, ''.join(MODES[Handler.mode]), 'text/event-stream')


def run(url):
    env = {**os.environ, 'AUTO_ONTOLOGY_API_URL': url, 'AUTO_ONTOLOGY_API_TOKEN': 'fake-token'}
    return subprocess.run([sys.executable, '-I', str(TOOL), '--question', 'q'], env=env, capture_output=True, text=True)


def main():
    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    failures = []

    Handler.mode = 'success'
    result = run(url)
    shown = json.loads(result.stdout) if result.returncode == 0 else {}
    if not (shown.get('row_count') == 2 and shown.get('sql', '').startswith('SELECT') and shown.get('answered_with_sql')):
        failures.append(f'success path wrong: rc={result.returncode} {result.stdout[:200]} {result.stderr[:200]}')
    elif '```sql\n' + shown['sql'].strip() + '\n```' not in shown.get('trace_markdown', ''):
        failures.append('trace_markdown does not hold the SQL: ' + shown.get('trace_markdown', '')[:200])

    # SQL text alone is not an answer: missing or unparseable rows are not answered, a valid empty list is
    for mode, answered in (('sql-no-rows', False), ('sql-bad-rows', False), ('sql-empty', True)):
        Handler.mode = mode
        result = run(url)
        shown = json.loads(result.stdout) if result.returncode == 0 else {}
        if shown.get('answered_with_sql') is not answered or not shown.get('sql'):
            failures.append(f'{mode}: expected answered_with_sql={answered}, got {result.stdout[:200]}')
        if not answered and ('no result rows' not in shown.get('trace_markdown', '') or 'no result rows' not in shown.get('note', '').replace('SQL but ', '')):
            failures.append(f'{mode}: the trace and note must say no rows came back: {shown.get("trace_markdown", "")[:120]} / {shown.get("note")}')
        if answered and shown.get('row_count') != 0:
            failures.append(f'{mode}: an empty result must count as zero rows, got {shown.get("row_count")}')

    for mode in ('cut', 'error', 'status-fail'):
        Handler.mode = mode
        result = run(url)
        if result.returncode != 1 or 'blocked' not in result.stderr or result.stdout.strip():
            failures.append(f'{mode}: expected exit 1 with "blocked", got rc={result.returncode} {result.stdout[:100]} {result.stderr[:100]}')

    server.shutdown()
    if failures:
        sys.exit('FAIL: ' + '; '.join(failures))
    print('ok')


if __name__ == '__main__':
    main()
