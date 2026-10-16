# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / 'files/skills/openshift-llm-deploy/scripts'


class DeploymentPlanTests(unittest.TestCase):
    def module(self):
        path = SCRIPTS / 'deploy-plan.py'
        self.assertTrue(path.exists(), 'The deterministic deployment handoff is missing')
        return runpy.run_path(str(path))

    def plan(self, module):
        options = {key: 'value' for key in module['REQUIRED_OPTIONS']}
        options.update({'namespace': 'models', 'release': 'qwen38-27b', 'platform': 'openshift'})
        return {'schemaVersion': 1, 'createdAt': int(time.time()), 'options': options,
                'expose': False, 'checks': {}}

    def test_complete_fixed_argv_keeps_namespace_and_release(self):
        module = self.module()
        command = module['deployment_command'](self.plan(module), 'models')
        self.assertEqual(command[0], 'sh')
        self.assertEqual(command[command.index('--namespace') + 1], 'models')
        self.assertEqual(command[command.index('--release') + 1], 'qwen38-27b')
        for key in module['REQUIRED_OPTIONS']:
            self.assertIn('--' + key, command)
        self.assertNotIn('--expose', command)

    def test_confirmed_route_exposure_is_forwarded_to_wrapper(self):
        module = self.module()
        plan = self.plan(module)
        plan['expose'] = True
        command = module['deployment_command'](plan, 'models')
        self.assertIn('--expose', command)

    def test_missing_input_and_wrong_target_fail_closed(self):
        module = self.module()
        plan = self.plan(module)
        with self.assertRaisesRegex(ValueError, 'namespace-mismatch'):
            module['deployment_command'](plan, 'different')
        del plan['options']['approved-vllm-image']
        with self.assertRaisesRegex(ValueError, 'invalid-plan-options'):
            module['deployment_command'](plan, 'models')

    def test_stale_plan_and_unknown_shell_option_are_rejected(self):
        module = self.module()
        plan = self.plan(module)
        plan['createdAt'] -= 1801
        with self.assertRaisesRegex(ValueError, 'plan-expired'):
            module['deployment_command'](plan, 'models')
        plan = self.plan(module)
        plan['options']['arbitrary-shell'] = 'bad'
        with self.assertRaisesRegex(ValueError, 'invalid-plan-options'):
            module['deployment_command'](plan, 'models')

    def test_hash_confirmation_and_preview_never_apply(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            payload = json.dumps(self.plan(module)).encode()
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            with mock.patch.dict(module['main'].__globals__, {'target_namespace': lambda: 'models'}), \
                 mock.patch.dict(module['main'].__globals__, {'run_deployment': mock.Mock()}) as _globals, \
                 mock.patch.object(module['sys'], 'argv', ['deploy-plan', '--plan', str(path), '--approved-plan-sha256', digest]):
                self.assertEqual(module['main'](), 0)
                module['main'].__globals__['run_deployment'].assert_not_called()
            with mock.patch.dict(module['main'].__globals__, {'run_deployment': mock.Mock()}), \
                 mock.patch.object(module['sys'], 'argv', ['deploy-plan', '--plan', str(path), '--approved-plan-sha256', '0' * 64, '--confirm']):
                self.assertEqual(module['main'](), 1)
                module['main'].__globals__['run_deployment'].assert_not_called()

    def test_structured_failure_is_not_success_when_wrapper_exits_zero(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            payload = json.dumps(self.plan(module)).encode()
            path.write_bytes(payload)
            with mock.patch.dict(module['main'].__globals__, {'target_namespace': lambda: 'models'}), \
                 mock.patch.dict(module['main'].__globals__, {'run_deployment': lambda command: subprocess.CompletedProcess(command, 0, 'DEPLOYMENT_RESULT=failed\n', '')}), \
                 mock.patch.object(module['sys'], 'argv', ['deploy-plan', '--plan', str(path), '--approved-plan-sha256', hashlib.sha256(payload).hexdigest(), '--confirm']):
                self.assertEqual(module['main'](), 1)

    def test_deployment_output_streams_and_ready_is_accepted(self):
        module = self.module()
        result = module['run_deployment']([module['sys'].executable, '-c', "print('DEPLOYMENT_RESULT=ready', flush=True)"])
        self.assertEqual(result.returncode, 0)
        self.assertIn('DEPLOYMENT_RESULT=ready', result.stdout)
