# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Publish a NeMo Compass insights.yml to Helix, so the findings appear in Studio.

Compass finding -> Helix Insight: name -> title, description -> description,
evidence trace IDs -> trace_refs. Helix has no CLI command for this yet.

  uv run --with pyyaml python publish.py insights.yml [--agent cad-agent]

Reads NHX_BASE_URL and NHX_WORKSPACE like the Helix CLI.
"""

import argparse
import json
import os
import urllib.request

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('insights', help='insights.yml written by insight-agent')
    parser.add_argument('--agent', default='cad-agent')
    args = parser.parse_args()
    base = os.environ.get('NHX_BASE_URL', 'http://localhost:8080').rstrip('/')
    url = f"{base}/apis/insights/v2/workspaces/{os.environ.get('NHX_WORKSPACE', 'default')}/insights"
    with open(args.insights) as f:
        for insight in yaml.safe_load(f) or []:
            body = {'title': insight['name'], 'agent': args.agent,
                    'description': insight['description'],
                    'trace_refs': [e['trace_id'] for e in insight['evidence']]}
            request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request) as response:
                print(json.load(response)['name'], insight['name'])


if __name__ == '__main__':
    main()
