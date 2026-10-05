# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline checks of verification verdicts. No real credentials or network calls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parents[1]
CURL = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert not any('synthetic-key' in x for x in a), 'credential in argv'
assert sys.stdin.read().strip() == 'Authorization: Bearer synthetic-key'
if '-w' in a:
    if any(x.endswith('/api/v1/tool-packs/') for x in a):
        print('403', end='')
    else:
        if a[a.index('-o') + 1] != '/dev/null':
            Path(a[a.index('-o') + 1]).write_text(os.environ.get('MOCK_DENIAL_BODY', ''))
        print(os.environ.get('MOCK_HTTP', '403'), end='')
        sys.exit(int(os.environ.get('MOCK_CURL_EXIT', '0')))
elif '-D' in a:
    Path(a[a.index('-D') + 1]).write_text('Mcp-Session-Id: test-session\r\n')
else:
    request = json.loads(a[a.index('--data') + 1])
    if request['method'] == 'tools/list':
        result = {'tools': [{'name': 'workday__list_workers'}]}
    elif request['params']['name'] == 'workday__request_one_time_payment':
        result = {'isError': True, 'content': [{'text': '{"error_reason":"tool_not_found"}'}]}
    else:
        if 'MOCK_READ' in os.environ:
            print(os.environ['MOCK_READ'])
            sys.exit(0)
        result = {'content': [{'text': 'synthetic worker'}]}
    print(json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': result}))
'''


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        shutil.copytree(RECIPE / 'scripts', root / 'scripts')
        self.script = root / 'scripts' / 'verify.sh'
        self.bin = root / 'bin'
        self.bin.mkdir()
        self.command('curl', CURL)
        self.command('openshell', '#!/bin/sh\necho merge-hr\n')
        self.command('nemoclaw', '#!/bin/sh\nprintf "%s" "$MOCK_TURN"\nexit "${MOCK_AGENT_EXIT:-0}"\n')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        MERGE_AH_MCP_TOKEN='synthetic-key', MERGE_AH_TOOL_PACK_ID='reader',
                        MERGE_AH_REGISTERED_USER_ID='synthetic-user', OTHER_TOOL_PACK_ID='other',
                        EXPECT_REVOKED='0', MOCK_TURN='Synthetic worker', AH_BASE_URL='https://example.invalid',
                        NEMOCLAW_SANDBOX_NAME='merge-hr', MOCK_HTTP='403', MOCK_CURL_EXIT='0',
                        MOCK_AGENT_EXIT='0')

    def command(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def run_verify(self, **settings):
        return subprocess.run(['bash', str(self.script)], env=dict(self.env, **settings),
                              text=True, capture_output=True, timeout=10)

    def test_revoked_key_uses_dedicated_mode(self):
        for status in ('401', '403'):
            with self.subTest(status=status):
                result = self.run_verify(EXPECT_REVOKED='1', MOCK_HTTP=status)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS  case 5', result.stdout)
                self.assertNotIn('case 1:', result.stdout)

    def test_revocation_requires_explicit_denial(self):
        for status, exit_code in [('200', '0'), ('404', '0'), ('500', '0'), ('000', '7')]:
            with self.subTest(status=status):
                result = self.run_verify(EXPECT_REVOKED='1', MOCK_HTTP=status, MOCK_CURL_EXIT=exit_code)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAIL  case 5', result.stdout)

    def test_cross_pack_requires_explicit_denial(self):
        for status, exit_code in [('200', '0'), ('404', '0'), ('500', '0'), ('000', '7')]:
            with self.subTest(status=status):
                result = self.run_verify(MOCK_HTTP=status, MOCK_CURL_EXIT=exit_code)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAIL  case 7', result.stdout)

    def test_cross_pack_denial_passes(self):
        result = self.run_verify(MOCK_HTTP='403')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS  case 7', result.stdout)

    def test_cross_pack_explicit_scope_404_passes(self):
        body = 'data: {"error":{"code":-32601,"message":"Resource not in API key scope."}}'
        result = self.run_verify(MOCK_HTTP='404', MOCK_DENIAL_BODY=body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS  case 7', result.stdout)
        result = self.run_verify(MOCK_HTTP='404', MOCK_DENIAL_BODY='{"error":{"code":-32601,"message":"Not found"}}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL  case 7', result.stdout)

    def test_agent_failure_and_empty_output_fail(self):
        for settings in [{'MOCK_AGENT_EXIT': '1'}, {'MOCK_TURN': ''}, {'MOCK_TURN': '  \n'}]:
            with self.subTest(settings=settings):
                result = self.run_verify(**settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAIL  case 4b', result.stdout)

    def test_malformed_read_cannot_pass(self):
        for payload in ('{}', '{"status":"ok"}', '{"result":{}}', '{"result":{"content":"invalid"}}'):
            with self.subTest(payload=payload):
                result = self.run_verify(MOCK_READ=payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAIL  case 4:', result.stdout)

    def test_teardown_propagates_remove_and_reset_failures(self):
        for failing in ('remove', 'reset'):
            with self.subTest(failing=failing):
                self.command('nemoclaw', '#!/bin/sh\ncase " $* " in *" ' + failing + ' "*) exit 1;; esac\n')
                result = subprocess.run(['bash', str(self.script.with_name('teardown.sh'))],
                                        env=self.env, text=True, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Removed 'merge-workday'", result.stdout)

    def test_text_alone_is_not_tool_use_evidence(self):
        result = self.run_verify()
        self.assertIn('SKIP  case 4b', result.stdout)
        self.assertNotIn('PASS  case 4b', result.stdout)


if __name__ == '__main__':
    unittest.main()
