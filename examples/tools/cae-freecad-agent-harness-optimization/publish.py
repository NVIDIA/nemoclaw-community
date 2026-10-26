# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Publish eval results and Compass findings to NeMo Helix.

  python publish.py scores JOB_DIR          # verifier results -> each run's Intake trace
  uv run --with pyyaml python publish.py insights insights.yml [--agent cad-agent]

scores: for every trial of a Harbor job, attaches the verifier's reward, IoU, failed
checks and model complexity (features, sketches, faces, ...) to the run's trace (its ID
from agent/outcome.json, else the first line of agent/run.log), so NeMo Compass sees how
each run was graded.
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
    """The verifier's reward, IoU, checks passed of total, failed checks and complexity
    counts for one trial."""
    verifier = trial / 'verifier'
    rows = (verifier / 'results').read_text().splitlines() if (verifier / 'results').exists() else []
    stats = verifier / 'metrics.json'
    metrics = json.loads(stats.read_text()) if stats.exists() else {}
    return {'reward': float((verifier / 'reward.txt').read_text()),
            'iou': metrics.pop('iou', None),  # not measured: no valid solid
            'checks': sum(row.endswith('\tPASS') for row in rows), 'of': len(rows),
            'failed': [row.split('\t')[0] for row in rows if row.endswith('\tFAIL')],
            'complexity': metrics}


def outcome(trial: Path) -> dict:
    """How the run ended (harness/run_agent.py): trace, ended, trace_delivered; {} if unknown."""
    path = trial / 'agent' / 'outcome.json'
    return json.loads(path.read_text()) if path.exists() else {}


# The agent's own outcome: it ran out of time, or exited non-zero (its own crash).
AGENT_EXCEPTIONS = {None, 'AgentTimeoutError', 'NonZeroAgentExitCodeError'}


def void_reason(trial: Path) -> str | None:
    """Why a run is VOID (lost to the infrastructure, so not counted), else None: a Harbor
    exception other than the agent's own (container, verifier time-out, GatewayLost), no
    grade, or the run lost to the model gateway (outcome.json `ended: gateway`)."""
    result = trial / 'result.json'
    if result.exists():
        error = (json.loads(result.read_text()).get('exception_info') or {}).get('exception_type')
        if error not in AGENT_EXCEPTIONS:
            return error
    if not (trial / 'verifier' / 'reward.txt').exists() or not (trial / 'verifier' / 'results').exists():
        return 'no grade'
    return 'gateway' if outcome(trial).get('ended') == 'gateway' else None


def trace_id(trial: Path) -> str | None:
    """The run's Intake trace ID: from outcome.json, else the `trace` line run_agent.py prints."""
    found, log = outcome(trial).get('trace'), trial / 'agent' / 'run.log'
    if not found and log.exists():
        line = re.search(r'^trace (\S+)$', log.read_text(errors='replace'), re.MULTILINE)
        found = line and line.group(1)
    return found


def scores(job: Path) -> None:
    for log in sorted(job.glob('*/agent/run.log')):
        trial = log.parent.parent
        session = trace_id(trial)
        if not session or not (trial / 'verifier' / 'reward.txt').exists():
            continue
        void = void_reason(trial)
        if void:  # not counted, so no grade on its trace: Compass does not judge it
            print(trial.name, session, 'skipped: void', void)
            continue
        try:
            span = api('intake', f'traces/{session}')['root_span_id']
        except urllib.error.HTTPError as error:  # e.g. a run killed before its trace was sent
            print(trial.name, session, 'skipped:', error)
            continue
        result = grade(trial)
        target = {'session_id': session, 'span_id': span}
        numbers = {'reward': result['reward'], 'iou': result['iou'],
                   **{f'complexity.{k}': v for k, v in result['complexity'].items()}}
        for name, value in numbers.items():
            if value is None:  # IoU the verifier could not measure
                continue
            api('intake', 'evaluator-results', {**target, 'name': name, 'data_type': 'NUMERIC',
                                                'value': value})
        api('intake', 'evaluator-results', {**target, 'name': 'failed-checks', 'data_type': 'TEXT',
                                            'string_value': ', '.join(result['failed']) or 'none'})
        print(trial.name, session, result)


def insights(path: Path, agent: str) -> None:
    import yaml

    for insight in yaml.safe_load(path.read_text()) or []:
        body = {'title': insight['name'], 'agent': agent, 'description': insight['description'],
                'trace_refs': [e['trace_id'] for e in insight['evidence']]}
        print(api('insights', 'insights', body)['id'], insight['name'])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('scores').add_argument('job', type=Path, help='a Harbor job folder')
    found = commands.add_parser('insights')
    found.add_argument('insights', type=Path, help='insights.yml written by compass')
    found.add_argument('--agent', default='cad-agent')
    args = parser.parse_args()
    if args.command == 'scores':
        scores(args.job)
    else:
        insights(args.insights, args.agent)


if __name__ == '__main__':
    main()
