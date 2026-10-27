# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Each Harbor task carries its own copy of the verifier (a task's tests/ must stand alone);
the copies must stay identical, and test.sh must list exactly the checks the verifier writes."""

import json
import re
import unittest
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / 'evals'
TASKS = sorted(p.parents[1] for p in EVALS.glob('*/*/tests/check_model.py'))  # evals/<split>/<task>


class EvalsInSyncTest(unittest.TestCase):
    def test_verifier_copies_identical(self):
        for name in ('check_model.py', 'iou_core.py', 'iou_math.py'):
            copies = {(task / 'tests' / name).read_text() for task in TASKS}
            self.assertEqual(len(copies), 1, name)

    def test_test_sh_lists_every_check(self):
        rows = set(re.findall(r'row\("([\w-]+)"', (TASKS[0] / 'tests' / 'check_model.py').read_text()))
        for task in TASKS:
            listed = re.search(r'for id in ([\w\s-]+); do', (task / 'tests' / 'test.sh').read_text())
            self.assertEqual(set(listed.group(1).split()), rows, task.name)

    def test_ref_faces_matches_the_oracle(self):
        manifest = json.loads((EVALS / 'manifest.json').read_text())
        for task in manifest['tasks']:
            test_sh = (EVALS / task['path'] / 'tests' / 'test.sh').read_text()
            faces = int(re.search(r'REF_FACES=(\d+)', test_sh).group(1))
            self.assertEqual(faces, task['controls']['oracle']['faces'], task['id'])


if __name__ == '__main__':
    unittest.main()
