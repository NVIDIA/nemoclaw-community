# SPDX-License-Identifier: Apache-2.0

"""Pinned OpenClaw installation, independent of application releases and vLLM."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import time
import urllib.request

import agent_runtime as r
import ops_common as c

NODE = '24.16.0'


def install_node():
    system = {'Linux': 'linux', 'Darwin': 'darwin'}.get(platform.system())
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x64'}.get(platform.machine())
    if not system or not arch:
        raise RuntimeError('This installer supports Linux/macOS on ARM64 or x64.')
    target = r.root() / 'node'
    if (target / 'bin/node').exists():
        return
    cache = r.root() / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    name = 'node-v' + NODE + '-' + system + '-' + arch + '.tar.gz'
    base = 'https://nodejs.org/dist/v' + NODE + '/'
    print('Installing private Node.js ' + NODE + ' (system Node is unchanged).', flush=True)
    checksums = urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60).read().decode()
    expected = next((line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name), None)
    if not expected:
        raise RuntimeError('Official Node checksum not found.')
    archive = cache / name
    urllib.request.urlretrieve(base + name, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Node archive checksum mismatch.')
    with tarfile.open(archive) as tar:
        prefix = name[:-7]
        for member in tar.getmembers():
            parts = member.name.split('/')
            if parts[0] != prefix or '..' in parts or member.isdev() or member.islnk():
                raise RuntimeError('Unexpected Node archive member.')
            if member.issym():
                # Official npm/npx symlinks must remain within the extracted Node directory.
                link = (cache / member.name).parent / member.linkname
                if (cache / prefix).resolve() not in link.resolve().parents:
                    raise RuntimeError('Node archive symlink escapes its directory.')
        tar.extractall(cache)
    os.replace(cache / prefix, target)


def setup():
    c.initialize()
    r.root().mkdir(parents=True, exist_ok=True, mode=0o700)
    install_node()
    package = r.root() / 'package'
    package.mkdir(exist_ok=True)
    manifest = package / 'node_modules/openclaw/package.json'
    if not manifest.exists() or c.read_json(manifest).get('version') != r.VERSION:
        print('Installing OpenClaw ' + r.VERSION + '. This is independent from your LLM.', flush=True)
        c.run([r.root() / 'node/bin/npm', 'install', '--prefix', package, '--omit=dev', '--no-audit', '--no-fund', 'openclaw@' + r.VERSION], env=r.environment())
    from research_search import PACKAGE, VERSION, configure
    plugin_manifest = package/'node_modules'/PACKAGE/'package.json'
    if not plugin_manifest.exists() or c.read_json(plugin_manifest).get('version') != VERSION:
        c.run([r.root()/'node/bin/npm', 'install', '--prefix', package, '--omit=dev', '--no-audit', '--no-fund', PACKAGE+'@'+VERSION], env=r.environment())
    with r.config_lock():
        config = c.read_json(r.config_path()) or r.initial_config()
        config.setdefault('skills', {}).setdefault('workshop', {})['autonomous'] = {'mode': 'off'}
        config['skills'].setdefault('load', {})['watch'] = False
        r.save_config(configure(config, r.root()))
    r.bootstrap_host()
    print(r.cli('config', 'validate'))
    print('OpenClaw is installed. Choose a model in the app settings, then start the agent runtime.')


def require_installed():
    if not r.config_path().is_file() or not (r.root() / 'package/node_modules/.bin/openclaw').exists():
        raise RuntimeError('Install the agent runtime first: ./bac dev setup')


def start():
    require_installed()
    try:
        r.gateway('/v1/models', timeout=2)
    except RuntimeError:
        pass
    else:
        print('OpenClaw is already reachable; its running sessions were left in place.')
        return
    if platform.system() == 'Darwin':
        from runtime_settings import start_gateway
        print(start_gateway().get('message', 'Agent runtime connected.'))
        return
    c.require_systemd()
    if not r.config_path().exists():
        raise RuntimeError('Run ./bac dev runtime setup first.')
    if c.active('bac-openclaw') and c.is_owned_unit('bac-openclaw'):
        print('OpenClaw is starting. Waiting for its existing service avoids interrupting sessions.')
        return
    if not c.port_free(r.gateway_port()):
        raise RuntimeError(f'Port {r.gateway_port()} is already used by another or still-starting runtime. Inspect ./bac dev runtime check before retrying.')
    print(r.cli('config', 'validate'))
    c.install_unit('bac-openclaw', [r.root() / 'package/node_modules/.bin/openclaw', 'gateway', 'run'],
                   {**c.service_environment(), **{k:v for k,v in r.environment().items() if k in ('PATH', 'NODE_OPTIONS', 'OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH', 'XDG_CONFIG_HOME')}})
    c.service('bac-openclaw', 'enable')
    c.service('bac-openclaw', 'start')
    print(f'OpenClaw starting on loopback port {r.gateway_port()}. ./bac dev runtime check shows readiness.')


def check(wait=0):
    require_installed()
    r.cli('config', 'validate', timeout=30)
    c.wait_ready(lambda: r.gateway('/v1/models', timeout=3), 'OpenClaw gateway', wait, 'bac-openclaw')


def openshell(action, automatic=False):
    if action == 'prove':
        from security_lab import prove
        return prove()
    if os.environ.get('BAC_CONTAINER') == '1':
        from agent_policy import configured, shell
        if not configured():
            raise RuntimeError('The bundled OpenShell configuration is unavailable. Check docker compose logs studio.')
        shell('sandbox', 'list')
        return
    from openshell_runtime import install, command as pinned_command, lock, environment
    command = pinned_command() if action == 'check' else install()
    current = c.read_json(r.config_path())
    selected = current.get('plugins', {}).get('entries', {}).get('openshell', {}).get('config', {})
    gateway_args = [value for field, flag in [('gateway', '--gateway'), ('gatewayEndpoint', '--gateway-endpoint'), ('workspace', '--workspace')]
                    if selected.get(field) for value in (flag, selected[field])]
    status = subprocess.run([command, *gateway_args, 'gateway', 'info'], env=environment(), capture_output=True, text=True, timeout=35)
    if status.returncode or not re.search(r'\bVersion:\s*' + re.escape(lock()['openshell']) + r'\b', re.sub(r'\x1b\[[0-9;]*m', '', status.stdout)):
        raise RuntimeError('The OpenShell gateway must also use ' + lock()['openshell'] + '. Update the selected gateway before enabling protection; other gateways were left unchanged.')
    # Listing registrations is not proof that the selected gateway is reachable.
    subprocess.run([command, *gateway_args, 'sandbox', 'list'], env=environment(), check=True, capture_output=True, timeout=35)
    if action == 'check':
        print(r.cli('sandbox', 'explain'))
        print(r.cli('sandbox', 'list'))
        return
    current = c.read_json(r.config_path())
    installed = current.get('plugins', {}).get('installs', {}).get('openshell', {})
    package = Path(installed.get('installPath') or r.root() / 'state/extensions/openshell') / 'package.json'
    if c.read_json(package, {}).get('version') != r.VERSION:
        operation = 'update' if installed else 'install'
        print(r.cli('plugins', operation, '@openclaw/openshell-sandbox@' + r.VERSION, timeout=240))
    with r.config_lock():
        config = c.read_json(r.config_path())
        previous = json.loads(json.dumps(config))
        from agent_policy import default_path, policy_document
        c.write_json(default_path(), policy_document())
        config['agents']['defaults']['sandbox'] = {'mode': 'off'}
        entry = config.setdefault('plugins', {}).setdefault('entries', {}).setdefault('openshell', {})
        entry['enabled'] = True
        entry.setdefault('config', {}).update({
            'command': str(Path(__file__).with_name('owned_openshell.py')), 'from': lock()['images']['openclaw'], 'mode': 'mirror', 'autoProviders': False, 'providers': [], 'policy': str(default_path())})
        config.setdefault('gateway', {}).setdefault('reload', {})['mode'] = 'hybrid'
        r.save_config(config)
        try:
            print(r.cli('config', 'validate'))
        except Exception:
            r.save_config(previous)
            raise
    # Plugin hot reload can report success while its sandbox backend is absent.
    # Ask the running gateway to drain active work and reload its plugin registry.
    # Merely listing models does not prove the OpenShell backend was registered.
    try:
        r.gateway('/v1/models', timeout=2)
    except RuntimeError:
        pass  # start_gateway below loads plugins on a fresh process.
    else:
        print(r.cli('gateway', 'restart', '--safe', timeout=45))
    time.sleep(2)
    settings_started = False
    from runtime_settings import start_gateway
    for attempt in range(30):
        try:
            r.gateway('/v1/models', timeout=2)
            break
        except RuntimeError:
            if not settings_started:
                start_gateway()
                settings_started = True
            time.sleep(1)
    else:
        raise RuntimeError('OpenShell is configured, but the agent runtime has not finished reconnecting.')
    print('OpenShell setup is saved and the agent gateway is reachable. New protected personal agents start with no outbound network permissions. Inspect each agent’s actual policy in the Lounge.')
