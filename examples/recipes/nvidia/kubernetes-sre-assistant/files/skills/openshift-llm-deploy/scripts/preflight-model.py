# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import argparse
import hashlib
import json
import math
import shlex
import re
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import yaml


class PreflightError(Exception):
    pass


def run_stage(command: list[str], deadline: float) -> dict[str, str]:
    budget = min(30, deadline - time.monotonic())
    if budget <= 0:
        raise PreflightError('preflight-total-timeout')
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=budget, check=False)
    except subprocess.TimeoutExpired as error:
        raise PreflightError('preflight-stage-timeout') from error
    except FileNotFoundError as error:
        raise PreflightError('installed-tool-missing') from error
    print(result.stdout, end='', flush=True)
    if result.returncode:
        print(result.stderr[:2000], end='', flush=True)
        raise PreflightError('preflight-stage-failed:' + Path(command[0]).name)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def build_plan(arguments, intake, storage, gpu, runtime, catalog) -> dict:
    memory_gib = max(16, math.ceil(int(storage['HF_MODEL_SOURCE_BYTES']) / (1024 ** 3)) + 16)
    options = {
        'namespace': arguments.namespace, 'release': arguments.release, 'model': arguments.model,
        'node': gpu['HF_GPU_SELECTED_NODE'], 'gpus': gpu['HF_GPU_COUNT'],
        'storage-class': arguments.storage_class, 'pvc-size': storage['HF_MODEL_RECOMMENDED_PVC_SIZE'],
        'memory-request': f'{memory_gib}Gi', 'memory-limit': f'{memory_gib * 2}Gi',
        'hf-secret': intake['secretName'], 'platform': arguments.platform,
        'model-revision': storage['HF_MODEL_REVISION'], 'recipe-url': runtime['VLLM_RECIPE_URL'],
        'approved-gpu-node': gpu['HF_GPU_SELECTED_NODE'], 'approved-gpu-count': gpu['HF_GPU_COUNT'],
        'approved-gpu-recipe-sha256': gpu['HF_GPU_RECIPE_SHA256'],
        'approved-gpu-product': gpu['HF_GPU_SELECTED_PRODUCT'],
        'max-model-len': str(arguments.max_model_len), 'deployment-mode': 'dynamo', 'dynamo-backend': 'vllm',
    }
    for option, field in (
        ('image', 'IMAGE'), ('source', 'IMAGE_SOURCE'), ('hardware-recipe-url', 'HARDWARE_RECIPE_URL'),
        ('hardware-recipe-sha256', 'HARDWARE_RECIPE_SHA256'), ('hardware-profile', 'HARDWARE_PROFILE'),
        ('profile-identity', 'PROFILE_IDENTITY'), ('args-sha256', 'ARGS_SHA256'), ('env-sha256', 'ENV_SHA256'),
    ):
        options['approved-vllm-' + option] = runtime['VLLM_' + field]
    if options['recipe-url'].startswith('chart-owned:'):
        options['approved-gpu-recipe-artifact'] = catalog['VLLM_RECIPE_ARTIFACT']
    return {'schemaVersion': 1, 'createdAt': int(time.time()), 'options': options,
            'expose': arguments.expose, 'checks': {'storage': storage, 'gpu': gpu, 'runtime': runtime,
                                                 'modelRunnerServiceAccount': intake['modelRunnerServiceAccount']}}


def resolve_deployment_identity(arguments) -> None:
    model = arguments.model.removeprefix('https://huggingface.co/').rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', model):
        raise PreflightError('invalid-huggingface-model-id')
    release = re.sub(r'[^a-z0-9]+', '-', model.split('/')[1].lower()).strip('-')
    if not release:
        raise PreflightError('invalid-model-release-name')
    if len(release) > 40:
        release = release[:31].rstrip('-') + '-' + hashlib.sha256(model.encode()).hexdigest()[:8]
    if arguments.release is not None and arguments.release != release:
        raise PreflightError('model-release-mismatch:expected-' + release)
    arguments.release = release
    arguments.model = model
    if arguments.expose is None:
        arguments.expose = arguments.platform == 'openshift'


def main() -> int:
    parser = argparse.ArgumentParser(description='Bounded read-only model preflight; never authorizes deployment.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--release', help='Optional model-derived release; mismatches are rejected.')
    parser.add_argument('--storage-class', required=True)
    parser.add_argument('--max-model-len', type=int, default=32768)
    parser.add_argument('--platform', choices=('openshift', 'kubernetes'), default='openshift')
    exposure = parser.add_mutually_exclusive_group()
    exposure.add_argument('--expose', dest='expose', action='store_true')
    exposure.add_argument('--no-expose', dest='expose', action='store_false')
    parser.set_defaults(expose=None)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.environ['PATH'] = '/chart-bin:/toolbox:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin'
    deadline = time.monotonic() + 120
    artifacts = Path(tempfile.mkdtemp(prefix='hermes-model-preflight-'))
    try:
        resolve_deployment_identity(arguments)
        defaults = yaml.safe_load((root / 'dynamo-defaults.yaml').read_text())
        intake = yaml.safe_load((root / 'hf-token-intake.yaml').read_text())
        target = ({'targetNamespace': intake['namespace']} if intake.get('namespace')
                  else yaml.safe_load((root / 'deployment-target.yaml').read_text()))
        if arguments.namespace != target['targetNamespace']:
            raise PreflightError('deployment-target-namespace-mismatch')
        runner = intake.get('modelRunnerServiceAccount')
        if not isinstance(runner, str) or len(runner) > 253 or not re.fullmatch(r'[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?', runner):
            raise PreflightError('model-runner-config-invalid')
        print('HF_PREFLIGHT_STAGE=model-runner', flush=True)
        try:
            run_stage(['/chart-bin/oc', '-n', arguments.namespace, 'get', 'serviceaccount', runner, '-o', 'name'], deadline)
        except PreflightError as error:
            raise PreflightError('model-runner-unavailable:' + arguments.namespace + '/' + runner) from error
        print('HF_PREFLIGHT_MODEL_RUNNER=' + runner, flush=True)
        if intake.get('requireTokenForHuggingFaceModels', True):
            print('HF_PREFLIGHT_STAGE=token', flush=True)
            run_stage(['/chart-bin/oc', '-n', arguments.namespace, 'get', 'secret',
                       intake['secretName'], '-o', 'name'], deadline)
        print('HF_PREFLIGHT_STAGE=storage', flush=True)
        storage = run_stage([sys.executable, str(root / 'scripts/plan-hf-storage.py'),
                             '--model', arguments.model, '--namespace', arguments.namespace,
                             '--release', arguments.release, '--storage-class', arguments.storage_class], deadline)
        print('HF_PREFLIGHT_STAGE=recipe', flush=True)
        catalog = run_stage([sys.executable, str(root / 'scripts/resolve-vllm-recipe.py'),
                             '--catalog-only', '--model', arguments.model,
                             '--overrides-file', str(root / 'dynamo-defaults.yaml'),
                             '--artifact-dir', str(artifacts)], deadline)
        print('HF_PREFLIGHT_STAGE=gpu', flush=True)
        gpu_command = [sys.executable, str(root / 'scripts/plan-hf-gpus.py'),
                       '--model', arguments.model, '--namespace', arguments.namespace,
                       '--max-model-len', str(arguments.max_model_len),
                       '--expected-revision', storage['HF_MODEL_REVISION'],
                       '--recipe-url', catalog['VLLM_RECIPE_URL']]
        if catalog['VLLM_RECIPE_URL'].startswith('chart-owned:'):
            gpu_command += ['--recipe-artifact', catalog['VLLM_RECIPE_ARTIFACT'],
                            '--recipe-artifact-sha256', catalog['VLLM_RECIPE_SHA256']]
        if defaults.get('allowOCSStorageTaintedNodes') is True:
            gpu_command.append('--allow-ocs-storage-tainted-nodes')
        gpu = run_stage(gpu_command, deadline)
        if gpu['HF_GPU_RECIPE_SHA256'] != catalog['VLLM_RECIPE_SHA256']:
            raise PreflightError('recipe-changed-during-preflight')
        print('HF_PREFLIGHT_STAGE=runtime', flush=True)
        runtime_command = [sys.executable, str(root / 'scripts/resolve-vllm-recipe.py'),
                           '--model', arguments.model, '--selected-product', gpu['HF_GPU_SELECTED_PRODUCT'],
                           '--gpu-count', gpu['HF_GPU_COUNT'], '--max-model-len', str(arguments.max_model_len),
                           '--default-image', defaults['standardVllmImage'],
                           '--overrides-file', str(root / 'dynamo-defaults.yaml'),
                           '--artifact-dir', str(artifacts)]
        if catalog['VLLM_RECIPE_URL'] != 'unavailable':
            runtime_command += ['--approved-recipe-url', catalog['VLLM_RECIPE_URL'],
                                '--approved-recipe-sha256', catalog['VLLM_RECIPE_SHA256']]
        if catalog['VLLM_RECIPE_URL'].startswith('chart-owned:'):
            runtime_command += ['--approved-planning-artifact', catalog['VLLM_RECIPE_ARTIFACT']]
        runtime = run_stage(runtime_command, deadline)
        plan = build_plan(arguments, intake, storage, gpu, runtime, catalog)
        payload = (json.dumps(plan, sort_keys=True, separators=(',', ':')) + '\n').encode()
        plan_path = artifacts / 'deployment-plan.json'
        with plan_path.open('xb') as destination:
            os.chmod(plan_path, 0o600)
            destination.write(payload)
        print('HF_PREFLIGHT_PLAN=' + str(plan_path))
        digest = hashlib.sha256(payload).hexdigest()
        print('HF_PREFLIGHT_PLAN_SHA256=' + digest)
        validation_command = shlex.join([sys.executable, str(root / 'scripts/deploy-plan.py'),
                                         '--plan', str(plan_path), '--approved-plan-sha256', digest])
        print('HF_PREFLIGHT_VALIDATE_COMMAND=' + validation_command)
        print('HF_PREFLIGHT_DEPLOY_COMMAND=' + validation_command + ' --confirm')
        print('HF_PREFLIGHT_NAMESPACE=' + arguments.namespace)
        print('HF_PREFLIGHT_RELEASE=' + arguments.release)
        print('HF_PREFLIGHT_MEMORY_REQUEST=' + plan['options']['memory-request'])
        print('HF_PREFLIGHT_MEMORY_LIMIT=' + plan['options']['memory-limit'])
        print('HF_PREFLIGHT_EXPOSE=' + str(arguments.expose).lower())
        print('HF_PREFLIGHT_STATUS=ready')
        print('HF_PREFLIGHT_FINAL_CONFIRMATION=required')
        return 0
    except (PreflightError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print('HF_PREFLIGHT_STATUS=blocked')
        print('HF_PREFLIGHT_REASON=' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
