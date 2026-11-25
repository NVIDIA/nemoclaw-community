# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Exercise credential continuity and workspace ownership before Docker writes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        original = Path(__file__).resolve().parent
        self.recipe = self.root / 'recipe'
        shutil.copytree(original, self.recipe / 'agent-configs',
                        ignore=shutil.ignore_patterns('.run', '.nemoclaw', '.env', 'state', '__pycache__'))
        shutil.copytree(original.parent / 'src', self.recipe / 'src')
        self.target = self.recipe / 'agent-configs'
        binary = self.root / 'bin'
        binary.mkdir()
        docker = binary / 'docker'
        docker.write_text('''#!/usr/bin/env bash
if [[ "$1 $2" == "volume inspect" ]]; then
  [[ -n "${TEST_VOLUME_OWNER:-}" ]] || exit 1
  if [[ "$*" == *--format* ]]; then printf '%s\\n' "$TEST_VOLUME_OWNER"; fi
  exit 0
fi
printf '%s\\n' "$*" >> "$TEST_DOCKER_WRITES"
''')
        docker.chmod(0o755)
        self.log = self.root / 'writes'
        self.env = dict(os.environ, PATH=f'{binary}:' + os.environ['PATH'],
                        TEST_DOCKER_WRITES=str(self.log))
        self.env.pop('TEST_VOLUME_OWNER', None)

    def prepare(self, workspace='nc-0123456789abcdef'):
        return subprocess.run(['bash', 'prepare.sh', workspace], cwd=self.target,
                              env=self.env, capture_output=True, text=True)

    def test_reuses_token_and_adapts_skill_to_read_only_mount(self):
        self.assertEqual(self.prepare().returncode, 0)
        token = self.target / '.run/worker-token'
        before = token.read_bytes()
        self.assertEqual(token.stat().st_mode & 0o777, 0o600)
        self.env['TEST_VOLUME_OWNER'] = 'nc-0123456789abcdef'
        self.assertEqual(self.prepare().returncode, 0)
        self.assertEqual(token.read_bytes(), before)
        self.assertEqual((self.target / '.run/stage/worker-token').read_bytes(), before)
        self.assertEqual((self.target / '.run/worker.env').read_text(),
                         'DEEPAGENTS_SERVICE_SECRET=' + before.decode())
        skill = (self.target / '.run/stage/skills/deep-research/SKILL.md').read_text()
        self.assertIn('/sandbox/research/deep-research', skill)
        self.assertNotIn('/sandbox/bin/deep-research', skill)

    def test_other_workspace_is_rejected_before_credentials_or_volume_writes(self):
        self.env['TEST_VOLUME_OWNER'] = 'nc-fedcba9876543210'
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('another workspace', result.stderr)
        self.assertFalse((self.target / '.run').exists())
        self.assertFalse(self.log.exists())

    def test_invalid_workspace_is_rejected_without_writes(self):
        self.assertNotEqual(self.prepare('wrong-workspace').returncode, 0)
        self.assertFalse((self.target / '.run').exists())
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
