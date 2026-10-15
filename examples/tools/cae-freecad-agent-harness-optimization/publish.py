# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Publish eval results and Compass findings to NeMo Helix.

  python publish.py scores JOB_DIR          # verifier results -> each run's Intake trace
  uv run --with pyyaml python publish.py insights insights.yml [--agent cad-agent]

scores: for every trial of a Harbor job, attaches the verifier's reward, IoU and failed
checks to the run's trace (its ID is the first line of agent/run.log), so NeMo
Compass sees how each run was graded.
insights: Compass finding -> Helix Insight (name -> title, evidence -> trace_refs);
Helix has no CLI command for this yet.

Reads NHX_BASE_URL and NHX_WORKSPACE like the Helix CLI. Re-running scores is safe:
Intake keeps one result per trace and name.
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get('NHX_BASE_URL', 'http://localhost:8080').rstrip('/')
WORKSPACE = os.environ.get('NHX_WORKSPACE', 'default')


def api(service: str, path: str, body: dict | None = None) -> dict:
    url = f'{BASE}/apis/{service}/v2/workspaces/{WORKSPACE}/{path}'
    request = urllib.request.Request(url, data=body and json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def grade(trial: Path) -> dict:
    """The verifier's reward, IoU and failed checks for one trial."""
    verifier = trial / 'verifier'
    log = (verifier / 'check.log').read_text() if (verifier / 'check.log').exists() else ''
    iou = re.search(r'^mesh-fidelity IoU ([\d.]+)', log, re.MULTILINE)
    rows = (verifier / 'results').read_text().splitlines() if (verifier / 'results').exists() else []
    return {'reward': float((verifier / 'reward.txt').read_text()),
            'iou': float(iou.group(1)) if iou else 0.0,
            'failed': [row.split('\t')[0] for row in rows if row.endswith('\tFAIL')]}


def trace_id(run_log: str) -> str | None:
    """The Intake trace ID that harness/run_agent.py prints first."""
    found = re.search(r'^trace (\S+)$', run_log, re.MULTILINE)
    return found and found.group(1)


def scores(job: Path) -> None:
    for log in sorted(job.glob('*/agent/run.log')):
        trial, session = log.parent.parent, trace_id(log.read_text())
        if not session or not (trial / 'verifier' / 'reward.txt').exists():
            continue
        try:
            span = api('intake', f'traces/{session}')['root_span_id']
        except urllib.error.HTTPError as error:  # e.g. a run killed before its trace was sent
            print(trial.name, session, 'skipped:', error)
            continue
        result = grade(trial)
        target = {'session_id': session, 'span_id': span}
        for name in ('reward', 'iou'):
            api('intake', 'evaluator-results', {**target, 'name': name, 'data_type': 'NUMERIC',
                                                'value': result[name]})
        api('intake', 'evaluator-results', {**target, 'name': 'failed-checks', 'data_type': 'TEXT',
                                            'string_value': ', '.join(result['failed']) or 'none'})
        print(trial.name, session, result)


def insights(path: Path, agent: str) -> None:
    import yaml

    for insight in yaml.safe_load(path.read_text()) or []:
        body = {'title': insight['name'], 'agent': agent, 'description': insight['description'],
                'trace_refs': [e['trace_id'] for e in insight['evidence']]}
        print(api('insights', 'insights', body)['name'], insight['name'])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('scores').add_argument('job', type=Path, help='a Harbor job folder')
    found = commands.add_parser('insights')
    found.add_argument('insights', type=Path, help='insights.yml written by insight-agent')
    found.add_argument('--agent', default='cad-agent')
    args = parser.parse_args()
    if args.command == 'scores':
        scores(args.job)
    else:
        insights(args.insights, args.agent)


if __name__ == '__main__':
    main()
