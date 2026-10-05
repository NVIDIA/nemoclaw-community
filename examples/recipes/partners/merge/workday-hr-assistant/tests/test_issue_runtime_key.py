# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Exercise key issuance without contacting Agent Handler."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parents[1]


class KeyIssuanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = root = Path(temporary.name)
        shutil.copytree(RECIPE / 'scripts', root / 'scripts')
        self.envfile = root / '.env'
        self.envfile.write_text('MERGE_AH_TOOL_PACK_ID=reader\n'
                                'MERGE_AH_REGISTERED_USER_ID=test-user\n'
                                'export MERGE_AH_ADMIN_KEY="old-management-\nvalue"\n'
                                'MERGE_AH_MCP_TOKEN=old-runtime-value\n')
        self.backup = root / '.env.bak'
        self.backup.write_text('MERGE_AH_ADMIN_KEY=backup-management-value\n')
        for path in (self.envfile, self.backup):
            path.chmod(0o644)
        bindir = root / 'bin'
        bindir.mkdir()
        curl = bindir / 'curl'
        curl.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['REQUEST_MARKER']).touch()
assert 'MERGE_AH_ADMIN_KEY' not in os.environ
assert 'entered-management-value' not in str(sys.argv)
assert sys.stdin.read().strip() == 'Authorization: Bearer entered-management-value'
body = json.loads(sys.argv[sys.argv.index('--data') + 1])
assert body['tool_pack_ids'] == ['reader']
assert body['registered_user_ids'] == ['test-user']
assert body['scopes'] == ['runtime:all']
assert type(body['expires_in']) is int
assert body['expires_in'] == int(os.environ.get('EXPECTED_TTL', '3600'))
if os.environ.get('MOCK_FAILURE'): sys.exit(22)
print(json.dumps({'key': "runtime-test-$(touch SHOULD_NOT_EXIST)'value"}))
''')
        curl.chmod(0o755)
        python = bindir / 'python3'
        python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$ARGV_LOG"\nexec ' +
                          shutil.which('python3') + ' "$@"\n')
        python.chmod(0o755)
        self.env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                        ARGV_LOG=str(root / 'argv.log'), REQUEST_MARKER=str(root / 'requested'))
        self.env.pop('MERGE_AH_KEY_TTL_SECONDS', None)

    def issue(self, **settings):
        return subprocess.run(['bash', str(self.root / 'scripts/issue-runtime-key.sh')],
                              input='entered-management-value\n', text=True,
                              capture_output=True, env=dict(self.env, **settings), cwd=self.root)

    def assert_management_removed(self):
        for path in (self.envfile, self.backup):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('MERGE_AH_ADMIN_KEY', path.read_text())
            self.assertNotIn('management-', path.read_text())

    def test_keys_use_stdin_expire_and_files_are_private(self):
        result = self.issue()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('entered-management-value', result.stdout + result.stderr)
        self.assertNotIn('runtime-test-', result.stdout + result.stderr)
        self.assertNotIn('runtime-test-', (self.root / 'argv.log').read_text())
        self.assert_management_removed()
        self.assertIn('MERGE_AH_MCP_TOKEN=old-runtime-value', self.backup.read_text())
        loaded = subprocess.run(['bash', '-c', '. "$1"; printf %s "$MERGE_AH_MCP_TOKEN"',
                                 'test', str(self.envfile)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(loaded.stdout, "runtime-test-$(touch SHOULD_NOT_EXIST)'value")
        self.assertFalse((self.root / 'SHOULD_NOT_EXIST').exists())

    def test_custom_expiry(self):
        result = self.issue(MERGE_AH_KEY_TTL_SECONDS='7200', EXPECTED_TTL='7200')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_expiry_fails_before_request(self):
        for ttl in ('0', '-1', '1.5', 'never'):
            with self.subTest(ttl=ttl):
                result = self.issue(MERGE_AH_KEY_TTL_SECONDS=ttl)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must be a positive integer', result.stderr)
                self.assertFalse((self.root / 'requested').exists())
                self.assert_management_removed()

    def test_api_failure_does_not_leave_management_key_in_files(self):
        result = self.issue(MOCK_FAILURE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assert_management_removed()
        self.assertIn('MERGE_AH_MCP_TOKEN=old-runtime-value', self.envfile.read_text())


if __name__ == '__main__':
    unittest.main()
