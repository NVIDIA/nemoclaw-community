# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


REQUIRED_OPTIONS = (
    'namespace', 'release', 'model', 'node', 'gpus', 'storage-class', 'pvc-size',
    'memory-request', 'memory-limit', 'hf-secret', 'platform', 'model-revision',
    'recipe-url', 'approved-gpu-node', 'approved-gpu-count',
    'approved-gpu-recipe-sha256', 'approved-gpu-product', 'approved-vllm-image',
    'approved-vllm-source', 'approved-vllm-hardware-recipe-url',
    'approved-vllm-hardware-recipe-sha256', 'approved-vllm-hardware-profile',
    'approved-vllm-profile-identity', 'approved-vllm-args-sha256',
    'approved-vllm-env-sha256',
)
OPTIONAL_OPTIONS = ('approved-gpu-recipe-artifact', 'max-model-len', 'deployment-mode', 'dynamo-backend')


def target_namespace() -> str:
    import yaml
    root = Path(__file__).resolve().parents[1]
    intake = yaml.safe_load((root / 'hf-token-intake.yaml').read_text())
    target = ({'targetNamespace': intake['namespace']} if intake.get('namespace')
              else yaml.safe_load((root / 'deployment-target.yaml').read_text()))
    return target['targetNamespace']


def deployment_command(plan: dict, target: str) -> list[str]:
    if set(plan) != {'schemaVersion', 'createdAt', 'options', 'expose', 'checks'} or plan['schemaVersion'] != 1:
        raise ValueError('invalid-plan-schema')
    if type(plan['createdAt']) is not int or not 0 <= time.time() - plan['createdAt'] <= 1800:
        raise ValueError('plan-expired-replan-and-confirm')
    options = plan['options']
    if not isinstance(options, dict) or not set(REQUIRED_OPTIONS) <= set(options) or set(options) - set(REQUIRED_OPTIONS + OPTIONAL_OPTIONS):
        raise ValueError('invalid-plan-options')
    if any(not isinstance(value, str) or not value or '\x00' in value or '\n' in value for value in options.values()):
        raise ValueError('invalid-plan-option-value')
    if not target or options['namespace'] != target:
        raise ValueError('deployment-target-namespace-mismatch')
    if type(plan['expose']) is not bool:
        raise ValueError('invalid-plan-exposure')
    command = ['sh', str(Path(__file__).resolve().with_name('deploy-model.sh'))]
    for key in REQUIRED_OPTIONS + OPTIONAL_OPTIONS:
        if key in options:
            command.extend(['--' + key, options[key]])
    if plan['expose']:
        command.append('--expose')
    return command


def run_deployment(command: list[str]) -> subprocess.CompletedProcess:
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True) as process:
        deadline = time.monotonic() + 540
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                    raise subprocess.TimeoutExpired(command, 540)
                for key, _events in selector.select(timeout=min(5, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    sys.stdout.write(chunk.decode('utf-8', errors='replace'))
                    sys.stdout.flush()
                    output.extend(chunk)
        return subprocess.CompletedProcess(command, process.wait(timeout=max(1, deadline - time.monotonic())),
                                           output.decode('utf-8', errors='replace'), '')


def main() -> int:
    parser = argparse.ArgumentParser(description='Deploy an exact reviewed preflight plan; default is validation only.')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--approved-plan-sha256', required=True)
    parser.add_argument('--confirm', action='store_true')
    arguments = parser.parse_args()
    try:
        payload = Path(arguments.plan).read_bytes()
        if len(payload) > 262144 or hashlib.sha256(payload).hexdigest() != arguments.approved_plan_sha256:
            raise ValueError('approved-plan-sha256-mismatch')
        plan = json.loads(payload)
        command = deployment_command(plan, target_namespace())
        if not arguments.confirm:
            print('DEPLOYMENT_PLAN_STATUS=validated')
            print('DEPLOYMENT_FINAL_CONFIRMATION=required')
            return 0
        result = run_deployment(command)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode or fields.get('DEPLOYMENT_RESULT') not in {'ready', 'pending'}:
            raise ValueError('deployment-wrapper-failed-or-missing-result')
        return 0
    except subprocess.TimeoutExpired:
        print('DEPLOYMENT_RESULT=pending')
        print('DEPLOYMENT_REASON=handoff-timeout-inspect-existing-resources-do-not-retry')
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('DEPLOYMENT_RESULT=failed')
        print('DEPLOYMENT_REASON=' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
