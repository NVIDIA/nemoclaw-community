# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Setup must create only the reader pack and verify its persisted allowlist."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_reader_creation_and_allowlist_validation(self):
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                shutil.copytree(RECIPE / 'scripts', root / 'scripts')
                command = root / 'curl'
                command.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert 'MERGE_AH_ADMIN_KEY' not in os.environ
assert sys.stdin.read().strip() == 'Authorization: Bearer synthetic-admin'
assert not any('synthetic-admin' in arg for arg in a)
p = Path(os.environ['REQUEST_FILE'])
if '--data' in a:
    assert not p.exists(), 'setup created more than one pack'
    p.write_text(a[a.index('--data') + 1])
    print('{"id":"reader"}')
else:
    tools = json.loads(p.read_text())['connectors'][0]['tool_names']
    if os.environ['MISMATCH'] == '1': tools.append('request_one_time_payment')
    print(json.dumps({'connectors':[{'tools':[{'name': t} for t in tools]}]}))
''')
                command.chmod(0o755)
                request = root / 'request.json'
                env = dict(os.environ, PATH=temp + os.pathsep + os.environ['PATH'],
                           MERGE_AH_ADMIN_KEY='stale-exported-admin', AH_BASE_URL='https://example.invalid',
                           REQUEST_FILE=str(request), MISMATCH=str(int(mismatch)))
                result = subprocess.run(['bash', str(root / 'scripts/setup-packs.sh')],
                                        env=env, input='synthetic-admin\n', capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, int(mismatch), result.stdout + result.stderr)
                self.assertNotIn('synthetic-admin', result.stdout + result.stderr)
                self.assertFalse((root / '.env').exists())
                self.assertFalse((root / '.env.bak').exists())
                body = json.loads(request.read_text())
                self.assertEqual(body['name'], 'workday-hr-reader')
                self.assertEqual(set(body['connectors'][0]['tool_names']), {
                    'list_workers', 'get_worker', 'list_organizations',
                    'get_organization_workers', 'get_absence_balances', 'list_time_off_entries'})
