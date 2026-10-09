# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import runpy
import subprocess
import unittest
import argparse
import contextlib
import io
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / 'files/skills/openshift-llm-deploy/scripts/preflight-model.py'


class ModelPreflightTests(unittest.TestCase):
    def test_release_defaults_to_model_and_openshift_route(self):
        module = runpy.run_path(str(SOURCE))
        arguments = argparse.Namespace(model='https://huggingface.co/Qwen/Qwen3.8-27B', release=None, platform='openshift', expose=None)
        module['resolve_deployment_identity'](arguments)
        self.assertEqual(arguments.release, 'qwen3-8-27b')
        self.assertEqual(arguments.model, 'Qwen/Qwen3.8-27B')
        self.assertTrue(arguments.expose)

    def test_ui_release_cannot_be_used_as_model_release(self):
        module = runpy.run_path(str(SOURCE))
        arguments = argparse.Namespace(model='Qwen/Qwen3.8-27B', release='hermes-webui', platform='openshift', expose=None)
        with self.assertRaisesRegex(module['PreflightError'], 'model-release-mismatch'):
            module['resolve_deployment_identity'](arguments)

    def test_internal_only_and_kubernetes_keep_exposure_disabled(self):
        module = runpy.run_path(str(SOURCE))
        for platform, expose in [('openshift', False), ('kubernetes', None)]:
            arguments = argparse.Namespace(model='example/model', release='model', platform=platform, expose=expose)
            module['resolve_deployment_identity'](arguments)
            self.assertFalse(arguments.expose)

    def test_long_model_names_have_stable_distinct_dns_releases(self):
        module = runpy.run_path(str(SOURCE))
        releases = []
        for suffix in ['a', 'b']:
            arguments = argparse.Namespace(model='example/' + 'Long.Model-' * 8 + suffix, release=None, platform='openshift', expose=None)
            module['resolve_deployment_identity'](arguments)
            self.assertLessEqual(len(arguments.release), 40)
            self.assertRegex(arguments.release, r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
            releases.append(arguments.release)
        self.assertNotEqual(*releases)

    def test_missing_runner_stops_before_token_or_model_planning(self):
        module = runpy.run_path(str(SOURCE))
        configuration = [{}, {'secretName': 'hf-token', 'modelRunnerServiceAccount': 'model-runner'}, {'targetNamespace': 'models'}]
        runner = mock.Mock(side_effect=module['PreflightError']('preflight-stage-failed:oc'))
        with mock.patch.object(module['sys'], 'argv', ['preflight', '--model', 'example/model', '--namespace', 'models',
                                                      '--release', 'model', '--storage-class', 'ceph']), \
             mock.patch.object(module['Path'], 'read_text', return_value='configuration'), \
             mock.patch.object(module['yaml'], 'safe_load', side_effect=configuration), \
             mock.patch.dict(module['main'].__globals__, {'run_stage': runner}):
            self.assertEqual(module['main'](), 1)
        self.assertEqual(runner.call_count, 1)
        self.assertIn('serviceaccount', runner.call_args.args[0])

    def test_plan_contains_complete_verified_deployment_inputs(self):
        module = runpy.run_path(str(SOURCE))
        self.assertIn('build_plan', module, 'Preflight does not persist the verified handoff')
        arguments = argparse.Namespace(model='example/model', namespace='models', release='model',
                                       storage_class='ceph', max_model_len=32768, platform='openshift', expose=False)
        storage = {'HF_MODEL_REVISION': 'a' * 40, 'HF_MODEL_SOURCE_BYTES': '55586114863',
                   'HF_MODEL_RECOMMENDED_PVC_SIZE': '120Gi'}
        gpu = {'HF_GPU_SELECTED_NODE': 'node', 'HF_GPU_COUNT': '1', 'HF_GPU_SELECTED_PRODUCT': 'NVIDIA-B200',
               'HF_GPU_RECIPE_SHA256': 'b' * 64}
        runtime = {key: 'verified' for key in ('VLLM_RECIPE_URL', 'VLLM_IMAGE', 'VLLM_IMAGE_SOURCE',
                   'VLLM_HARDWARE_RECIPE_URL', 'VLLM_HARDWARE_RECIPE_SHA256', 'VLLM_HARDWARE_PROFILE',
                   'VLLM_PROFILE_IDENTITY', 'VLLM_ARGS_SHA256', 'VLLM_ENV_SHA256')}
        plan = module['build_plan'](arguments, {'secretName': 'hf-token', 'modelRunnerServiceAccount': 'model-runner'}, storage, gpu, runtime, {})
        self.assertEqual(plan['options']['namespace'], 'models')
        self.assertEqual(plan['options']['pvc-size'], '120Gi')
        self.assertEqual(plan['options']['memory-request'], '68Gi')
        self.assertEqual(plan['options']['approved-vllm-image'], 'verified')
        self.assertFalse(plan['expose'])

    def test_full_preflight_keeps_revision_and_recipe_gates(self):
        module = runpy.run_path(str(SOURCE))
        results = [
            {},
            {}, {'HF_MODEL_REVISION': 'a' * 40, 'HF_MODEL_SOURCE_BYTES': '55586114863', 'HF_MODEL_RECOMMENDED_PVC_SIZE': '120Gi'},
            {'VLLM_RECIPE_URL': 'https://recipes.vllm.ai/example/model.json', 'VLLM_RECIPE_SHA256': 'b' * 64},
            {'HF_GPU_RECIPE_SHA256': 'b' * 64, 'HF_GPU_SELECTED_PRODUCT': 'NVIDIA-B200', 'HF_GPU_COUNT': '1', 'HF_GPU_SELECTED_NODE': 'node'},
            {key: 'verified' for key in ('VLLM_RECIPE_URL', 'VLLM_IMAGE', 'VLLM_IMAGE_SOURCE',
             'VLLM_HARDWARE_RECIPE_URL', 'VLLM_HARDWARE_RECIPE_SHA256', 'VLLM_HARDWARE_PROFILE',
             'VLLM_PROFILE_IDENTITY', 'VLLM_ARGS_SHA256', 'VLLM_ENV_SHA256')},
        ]
        configuration = [{'standardVllmImage': 'image@sha256:' + 'c' * 64}, {'secretName': 'hf-token', 'modelRunnerServiceAccount': 'model-runner'}, {'targetNamespace': 'models'}]
        with mock.patch.object(module['sys'], 'argv', ['preflight', '--model', 'example/model', '--namespace', 'models',
                                                      '--release', 'model', '--storage-class', 'ceph']), \
             mock.patch.object(module['Path'], 'read_text', return_value='configuration'), \
             mock.patch.object(module['yaml'], 'safe_load', side_effect=configuration), \
             mock.patch.dict(module['main'].__globals__, {'run_stage': mock.Mock(side_effect=results)}):
            runner = module['main'].__globals__['run_stage']
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(module['main'](), 0)
            commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn('HF_PREFLIGHT_VALIDATE_COMMAND=', output.getvalue())
        self.assertIn('HF_PREFLIGHT_DEPLOY_COMMAND=', output.getvalue())
        self.assertEqual(commands[0][:6], ['/chart-bin/oc', '-n', 'models', 'get', 'serviceaccount', 'model-runner'])
        self.assertEqual(commands[1][:5], ['/chart-bin/oc', '-n', 'models', 'get', 'secret'])
        self.assertIn('--expected-revision', commands[4])
        self.assertIn('--approved-recipe-sha256', commands[5])

    def test_read_only_stages_are_bounded_and_use_installed_tools(self):
        module = runpy.run_path(str(SOURCE))
        with mock.patch.object(module['subprocess'], 'run', return_value=subprocess.CompletedProcess([], 0, stdout='KEY=value\n', stderr='')) as runner:
            result = module['run_stage'](['/chart-bin/oc', 'get', 'pvc'], module['time'].monotonic() + 60)
        self.assertEqual(result, {'KEY': 'value'})
        self.assertLessEqual(runner.call_args.kwargs['timeout'], 30)

    def test_timeout_is_a_clear_preflight_failure(self):
        module = runpy.run_path(str(SOURCE))
        with mock.patch.object(module['subprocess'], 'run', side_effect=subprocess.TimeoutExpired('oc', 30)):
            with self.assertRaisesRegex(module['PreflightError'], 'preflight-stage-timeout'):
                module['run_stage'](['/chart-bin/oc', 'get', 'pvc'], module['time'].monotonic() + 60)

    def test_execution_has_no_deployment_mutation_stage(self):
        source = SOURCE.read_text()
        self.assertNotIn('deploy-model.sh', source)
        self.assertNotIn("'apply'", source)
        self.assertIn('HF_PREFLIGHT_STATUS', source)
