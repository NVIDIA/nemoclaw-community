# SPDX-License-Identifier: Apache-2.0

"""Operator-only OpenShell probe. Never exposes a shell or policy editor to attendees.

Contract checked against NVIDIA/OpenShell v0.1.4,
examples/sandbox-policy-quickstart/{demo.sh,policy.yaml}. No credentials or user data
are attached to the fixed public GET requests. This probes a separate sandbox,
not the OpenClaw agent's sandbox or the host-side web tools.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time

import ops_common as c
import openshell_runtime
import agent_policy

SOURCE = 'https://github.com/NVIDIA/OpenShell/tree/v0.1.4/examples/sandbox-policy-quickstart'
STEPS = [('blocked', 'api.github.com'), ('allowed', 'api.github.com'), ('still-blocked', 'example.com')]


def policy(allow=False):
    # Policy schema/default filesystem fields from the Apache-2.0 upstream example.
    # SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
    # SPDX-License-Identifier: Apache-2.0 (policy template; see src/vendor/OpenShell-LICENSE.txt)
    base = '''version: 1
filesystem_policy:
  include_workdir: true
  read_only: [/usr, /lib, /proc, /dev/urandom, /app, /etc, /var/log]
  read_write: [/sandbox, /tmp, /dev/null]
landlock:
  compatibility: best_effort
'''
    return base + ('''network_policies:
  bac_public_read:
    name: bac-public-read
    endpoints:
      - host: api.github.com
        port: 443
        protocol: rest
        enforcement: enforce
        access: read-only
    binaries:
      - { path: /usr/bin/curl }
''' if allow else 'network_policies: {}\n')


def matching_log(logs, host, action):
    """Require a policy decision for the exact host and binary, not any curl error."""
    clean = re.sub(r'\x1b\[[0-9;]*m', '', logs)
    token = r'(?:action[=:]\s*"?' + action + r'\b|\b' + ('DENIED' if action == 'deny' else 'ALLOWED') + r'\b)'
    for line in clean.splitlines():
        if re.search(r'(?<![A-Za-z0-9_.-])' + re.escape(host) + r'(?![A-Za-z0-9_.-])', line) and '/usr/bin/curl' in line and re.search(token, line, re.I):
            return {'action': action, 'host': host, 'port': 443, 'binary': '/usr/bin/curl',
                    'lineSHA256': hashlib.sha256(line.encode()).hexdigest()}
    return None


def classify(host, expected, returncode, output, logs):
    action = 'allow' if expected == 'allowed' else 'deny'
    evidence = matching_log(logs, host, action)
    codes = re.findall(r'BAC_HTTP=(\d{3})', output)
    http = int(codes[-1]) if codes else 0
    if action == 'allow':
        passed = returncode == 0 and 200 <= http < 300 and bool(evidence)
    else:
        passed = returncode != 0 and bool(evidence)
    return {'id': expected, 'host': host, 'method': 'GET', 'passed': passed,
            'outcome': action if passed else 'unverified', 'exitCode': returncode,
            'httpStatus': http, 'logEvidence': evidence, 'checkedAt': time.time()}


def public_report(directory):
    path = Path(directory) / 'security-report.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        return {'status': 'not-captured', 'scope': 'Dedicated OpenShell proof sandbox', 'steps': []}
    try:
        result = json.loads(path.read_text())
        if result.get('schema') != 1 or result.get('source') != SOURCE:
            raise ValueError('Unsupported capture')
        return result
    except (ValueError, OSError):
        return {'status': 'unreadable', 'scope': 'Dedicated OpenShell proof sandbox', 'steps': []}


def prove():
    if not shutil.which('ssh'):
        raise RuntimeError('Install OpenShell and start its gateway first. No enforcement evidence was captured.')
    directory = c.initialize() / 'studio'
    directory.mkdir(exist_ok=True, mode=0o700)
    name = 'bac-proof-' + secrets.token_hex(4)
    binary = openshell_runtime.command()
    config = agent_policy.plugin_config().get('config', {})
    selected = []
    for key, flag in [('gateway', '--gateway'), ('gatewayEndpoint', '--gateway-endpoint'), ('workspace', '--workspace')]:
        if config.get(key): selected += [flag, config[key]]
    capture = directory / 'security-captures' / name
    capture.mkdir(parents=True, mode=0o700)
    report = {'schema': 1, 'source': SOURCE, 'status': 'running', 'sandbox': name,
              'scope': 'Dedicated OpenShell proof sandbox, separate from participant agents',
              'started': time.time(), 'steps': [], 'cleanedUp': False}

    def publish():
        c.write_json(directory / 'security-report.json', report)
        os.chmod(directory / 'security-report.json', 0o600)

    def run(label, args, timeout=30, required=True):
        if args[0] == 'openshell':
            args = [binary, *([] if args[1:] == ['--version'] else selected), *args[1:]]
        result = subprocess.run([str(a) for a in args], env=openshell_runtime.environment(), capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        (capture / (label + '.txt')).write_text(output)
        if required and result.returncode:
            raise RuntimeError(label + ' failed. Inspect the operator capture directory; no success was inferred.')
        return result, output

    attempted = created = False
    publish()
    print('OpenShell proof: fixed public GET requests in a fresh isolated sandbox. No participant policies change.', flush=True)
    print('Operator evidence directory:', capture, flush=True)
    try:
        _, version = run('version', ['openshell', '--version'])
        report['version'] = version.strip()[:120]
        deny_path, allow_path = capture / 'deny.yaml', capture / 'allow.yaml'
        deny_path.write_text(policy(False))
        allow_path.write_text(policy(True))
        report['policySHA256'] = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in [('before', deny_path), ('after', allow_path)]}
        attempted = True
        run('create', ['openshell', 'sandbox', 'create', '--name', name, '--policy', deny_path,
                       '--from', openshell_runtime.lock()['images']['openclaw'],
                       '--no-auto-providers', '--detach', '--', 'sleep', 'infinity'], timeout=180)
        created = True
        config, _ = run('ssh-config', ['openshell', 'sandbox', 'ssh-config', name])
        ssh_path = capture / 'ssh-config'
        ssh_path.write_text(config.stdout)
        os.chmod(ssh_path, 0o600)
        hosts = re.findall(r'^Host\s+([A-Za-z0-9_.-]+)\s*$', config.stdout, re.M)
        if not hosts:
            raise RuntimeError('OpenShell did not return a usable SSH host.')
        ssh = ['ssh', '-F', ssh_path, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', hosts[0]]
        ready = False
        for attempt in range(10):
            result, _ = run('ssh-ready', ssh + ['true'], required=False, timeout=15)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise RuntimeError('Sandbox connection timed out. This is not evidence of policy denial.')
        for index, (step, host) in enumerate(STEPS):
            if index == 1:
                run('policy-set', ['openshell', 'policy', 'set', name, '--policy', allow_path, '--wait'], timeout=60)
                report['policyChangedAt'] = time.time()
            print('Checking:', step, host, flush=True)
            # All remote arguments are fixed constants. No participant-controlled command is accepted.
            result, output = run(step, ssh + ['/usr/bin/curl -sSf --max-time 15 -o /dev/null '
                                      '-w "BAC_HTTP=%{http_code}" https://' + host + ('/zen' if host == 'api.github.com' else '/')], required=False)
            verdict = None
            for attempt in range(5):
                time.sleep(1)
                _, logs = run(step + '-logs', ['openshell', 'logs', name, '--since', '10m', '-n', '200'])
                verdict = classify(host, step, result.returncode, output, logs)
                if verdict['passed']:
                    break
            report['steps'].append(verdict)
            publish()
            if not verdict['passed']:
                raise RuntimeError('Request or matching policy log was not verified for ' + step + '. No enforcement success is claimed.')
        report['status'] = 'captured'
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report['status'] = 'incomplete'
        report['error'] = str(error)[:400] if isinstance(error, RuntimeError) else 'A command failed or timed out. Inspect the host capture; no policy result was inferred.'
        raise RuntimeError(report['error']) from error
    finally:
        if report['status'] == 'running':
            report.update(status='incomplete', error='Capture was interrupted before every check completed.')
        # A failed create might indicate a name conflict. Never delete a sandbox
        # unless this process observed its successful creation.
        if created:
            try:
                result, _ = run('cleanup', ['openshell', 'sandbox', 'delete', name], required=False, timeout=45)
                report['cleanedUp'] = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        report['finished'] = time.time()
        publish()
        c.write_json(capture / 'report.json', report)
        if attempted and not report['cleanedUp']:
            print('Cleanup needs attention. Inspect ownership before removing this sandbox: ' + name, flush=True)
    print('Proof captured. In Multi-Agent Studio, open Security lab → Refresh host evidence.', flush=True)
