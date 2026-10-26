# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for how publish.py reads a Harbor trial (its trace ID and the verifier's grade)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish  # noqa: E402
from publish import grade, trace_id  # noqa: E402


class TraceIdTest(unittest.TestCase):
    def trial(self, log: str, outcome: dict | None = None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / 'agent').mkdir()
        (root / 'agent' / 'run.log').write_text(log)
        if outcome is not None:
            (root / 'agent' / 'outcome.json').write_text(json.dumps(outcome))
        return root

    def test_outcome_first(self):
        trial = self.trial('trace 01a1-x\n', {'trace': '02b2-y', 'ended': 'done',
                                               'trace_delivered': True})
        self.assertEqual(trace_id(trial), '02b2-y')

    def test_first_trace_line(self):
        self.assertEqual(trace_id(self.trial('trace 01a1-x\nstopped after 300 s\n')), '01a1-x')

    def test_missing(self):
        self.assertIsNone(trace_id(self.trial('Traceback (most recent call last):\n')))


class VoidTest(unittest.TestCase):
    def trial(self, exception: str | None, ended: str | None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / 'verifier').mkdir()
        (root / 'verifier' / 'reward.txt').write_text('0\n')
        (root / 'verifier' / 'results').write_text('iou\tFAIL\n')
        (root / 'result.json').write_text(json.dumps(
            {'exception_info': exception and {'exception_type': exception}}))
        if ended:
            (root / 'agent').mkdir()
            (root / 'agent' / 'outcome.json').write_text(json.dumps({'ended': ended}))
        return root

    def test_graded_run_counts(self):
        self.assertIsNone(publish.void_reason(self.trial(None, 'timeout')))

    def test_infrastructure_error_is_void(self):
        self.assertEqual(publish.void_reason(self.trial('GatewayLost', None)), 'GatewayLost')

    def test_agent_crash_named_by_its_output_counts(self):
        # Harbor calls a crash whose traceback mentions a rate limit ApiRateLimitError.
        self.assertIsNone(publish.void_reason(self.trial('ApiRateLimitError', 'crash')))

    def test_gateway_outcome_is_void(self):
        self.assertEqual(publish.void_reason(self.trial(None, 'gateway')), 'gateway')


class GradeTest(unittest.TestCase):
    def trial(self, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / 'verifier').mkdir()
        for name, text in files.items():
            (root / 'verifier' / name).write_text(text)
        return root

    def test_verifier_output(self):
        trial = self.trial({
            'reward.txt': '0\n',
            'results': 'single-valid-solid\tPASS\nsingle-visible-object\tFAIL\n',
            'metrics.json': '{"iou": 0.9321, "features": 3, "faces": 7}'})
        self.assertEqual(grade(trial), {'reward': 0.0, 'iou': 0.9321, 'checks': 1, 'of': 2,
                                        'failed': ['single-visible-object'],
                                        'complexity': {'features': 3, 'faces': 7}})

    def test_no_model(self):
        # No model saved: the verifier writes only the reward and failing rows.
        trial = self.trial({'reward.txt': '0\n', 'results': 'mesh-fidelity\tFAIL\n'})
        self.assertEqual(grade(trial), {'reward': 0.0, 'iou': None, 'checks': 0, 'of': 1,
                                        'failed': ['mesh-fidelity'], 'complexity': {}})


if __name__ == '__main__':
    unittest.main()
