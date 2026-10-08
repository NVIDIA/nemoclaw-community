# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Bounded recovery must precede a human escalation, including after restart."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.environ.get('SRE_AUTOHEAL_TEST_SOURCE', str(Path(__file__).resolve().parents[1] / 'charts/sre-autoheal-agent/files/agent')))
from sre_autoheal.config import Config
from sre_autoheal.engine import Engine
from sre_autoheal.memory import Memory
from sre_autoheal.models import ActionResult, Diagnosis, Finding, Resource
from sre_autoheal.notify import Notifier


class AuditSink:
    name = 'email'
    def __init__(self):
        self.messages = []
    def send(self, message):
        self.messages.append(message)
        return True


class RecoveryEpisodeTests(unittest.TestCase):
    def test_three_unverified_deployment_recoveries_then_one_email(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Config()
            config.data['policy'].update(mode='safe', cooldown_seconds=0, retry_delay_seconds=0,
                                         tier_overrides={'restart_pod': 'SAFE'})
            config.data['memory'].update(backend='file', path=str(Path(directory) / 'memory.json'))
            sink = AuditSink()
            notifier = Notifier([sink], ['escalated'])
            finding = Finding('pod-crashloop', 'high', Resource('Pod', 'model-1', 'test'), 'CrashLoop',
                              owner=Resource('Deployment', 'model', 'test'),
                              evidence={'logs_tail': 'model initialization failed\npassword=secret-value'})
            snap = SimpleNamespace(errors=[], workload_labels=lambda subject: ({}, {}))
            results = []
            with patch('sre_autoheal.engine.verify_resolved', return_value=(False, 'Deployment still 0/1')):
                for attempt in range(4):
                    # A new engine reloads the real persisted budget each time.
                    memory = Memory.build(config.section('memory'))
                    engine = Engine(config, object(), None, memory, notifier, None)
                    engine.diagnose = lambda finding, history: Diagnosis('transient failure', 1.0, 'restart_pod')
                    with patch.object(engine.executor, 'execute', return_value=ActionResult(True, 'pod recreated')) as execute:
                        result = engine.handle_finding(finding, snap)
                        memory.save()
                        results.append(result.decision)
                        self.assertEqual(execute.call_count, 1 if attempt < 3 else 0)
            self.assertEqual(results, ['retry_pending', 'retry_pending', 'heal_failed', 'heal_failed'])
            self.assertEqual(len(sink.messages), 1)
            self.assertIn('0/1', sink.messages[0].text)
            self.assertIn('3/3', sink.messages[0].text)
            self.assertIn('model initialization failed', sink.messages[0].text)
            self.assertNotIn('secret-value', sink.messages[0].text)
            self.assertTrue(all('logs_tail' not in item['finding']['evidence']
                                for item in memory.data['incidents']))


if __name__ == '__main__':
    unittest.main()
