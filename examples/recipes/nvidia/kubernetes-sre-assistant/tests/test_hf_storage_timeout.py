# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock


class StorageTimeoutTests(unittest.TestCase):
    def test_storage_api_calls_have_a_bounded_timeout(self):
        path = Path(__file__).resolve().parents[1] / 'files/skills/openshift-llm-deploy/scripts/plan-hf-storage.py'
        spec = importlib.util.spec_from_file_location('storage_timeout_planner', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('oc', 30)) as runner:
            with self.assertRaisesRegex(module.PlannerError, 'cluster-inspection-timeout'):
                module.oc_json(['get', 'pvc'])
        self.assertEqual(runner.call_args.kwargs['timeout'], 30)
