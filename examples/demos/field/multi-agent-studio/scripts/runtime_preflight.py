# SPDX-License-Identifier: Apache-2.0

"""Read-only host checks before a Spark/Ubuntu protected-demo rehearsal.

This is infrastructure evidence, not a claim that a model or sandbox ran.
"""
import json
import platform
import shutil
import subprocess

import agent_runtime as runtime
import ops_common as common


def collect(protected=False):
    checks = []

    def check(name, probe, remedy):
        try:
            detail = probe()
            checks.append({'check': name, 'passed': True, 'detail': detail})
        except Exception:
            # Command output/config may contain secrets. Only public remediation is returned.
            checks.append({'check': name, 'passed': False, 'remedy': remedy})

    def command(args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=40).stdout.strip()

    def native():
        package = common.read_json(runtime.root() / 'package/node_modules/openclaw/package.json', {})
        if package.get('version') != runtime.VERSION:
            raise RuntimeError('Pinned runtime missing')
        runtime.cli('config', 'validate', timeout=30)
        return 'Pinned OpenClaw ' + runtime.VERSION + '; config validated'

    def gateway():
        runtime.gateway('/v1/models', timeout=4)
        return 'Agent gateway reachable; this does not test the model provider'

    check('OpenClaw installation and configuration', native, 'Run ./bac dev setup, then retry this check.')
    check('Running OpenClaw gateway', gateway, 'Run ./bac dev runtime start; inspect ./bac dev runtime logs if it fails. For foreground mode, use Settings > Model > Start agents.')
    if platform.system() == 'Linux':
        def user_service():
            if not common.systemd_available():
                raise RuntimeError('No user service session')
            return 'systemd user session available'
        check('Linux user service session', user_service, 'Log in through SSH as the normal account (not sudo). Without systemd, use ./bac dev preview; this service check is not applicable to foreground mode.')
    if protected:
        if platform.system() == 'Linux':
            def docker():
                version = command(['docker', 'version', '--format', '{{.Server.Version}}'])
                if int(version.split('.')[0]) < 28:
                    raise RuntimeError('Docker server too old')
                return 'Docker Engine ' + version + '; daemon accessible to this account'
            check('Docker Engine 28+ (Spark/Ubuntu Docker path)', docker, 'Run docker version and docker info as the same account. Start Docker, update an older engine, or fix account access; log in again after group changes.')

        def shell():
            from agent_policy import configured, plugin_config
            if not configured():
                raise RuntimeError('Protection configuration incomplete')
            cli = plugin_config()['config'].get('command', 'openshell')
            if not shutil.which('ssh'):
                raise RuntimeError('SSH client missing')
            command([cli, 'sandbox', 'list'])
            return 'OpenShell gateway reachable; default policy configured; SSH client available'
        check('OpenShell gateway and policy configuration', shell, 'Follow docs/ubuntu-setup.md#optional-openshell, confirm openshell status, then run ./bac dev openshell enable.')

        def plugin():
            data = json.loads(runtime.cli('plugins', 'list', '--json', timeout=40))
            entry = next(p for p in data.get('plugins', []) if p.get('id') == 'openshell')
            if not entry.get('enabled') or entry.get('status') != 'loaded' or entry.get('error'):
                raise RuntimeError('Plugin discovery failed')
            return 'Plugin discovery passed; only a protected run verifies the live backend'
        check('OpenClaw OpenShell plugin discovery', plugin, 'Run ./bac dev openshell enable. If it fails, inspect ./bac dev runtime logs and openshell status.')
    return {'host': platform.system() + ' ' + platform.machine(),
            'checks': checks, 'infrastructurePassed': all(c['passed'] for c in checks),
            'liveProtectedRunVerified': False,
            'next': ['Connect the model in the running app (API keys are session-only).',
                     'Run a personal agent and confirm a real model reply.',
                     *(['Run an OpenShell-on agent with a file-reading task; verify its actual sandbox and loaded policy.',
                        'Run ./bac dev openshell prove to capture independent deny/allow/deny policy evidence.'] if protected else [])]}


def run(protected=False):
    result = collect(protected)
    print(json.dumps(result, indent=2))
    if not result['infrastructurePassed']:
        raise RuntimeError('Preflight failed. Follow each failed check’s remedy; see docs/ubuntu-setup.md.')
