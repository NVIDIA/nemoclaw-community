# SPDX-License-Identifier: Apache-2.0

"""Container lifecycle only; model serving remains outside this stack."""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time

import agent_runtime as runtime
import ops_common as common

IMAGE_RUNTIME = Path('/opt/bac/runtime')
GATEWAY_STATE = Path('/var/lib/bac-openshell')
CLIENT_CERTS = Path('/run/bac-client')
LOCK_PATH = common.REPO / 'docker/runtime-lock.json'
UID = GID = 10001


def ports():
    values = [int(os.environ.get(key, default)) for key, default in (
        ('PORT', '8080'), ('BAC_OPENCLAW_PORT', '28689'),
        ('BAC_OPENSHELL_PORT', '28680'), ('BAC_OPENSHELL_HEALTH_PORT', '28681'))]
    if len(set(values)) != 4 or any(not 1024 <= p <= 65535 for p in values):
        raise RuntimeError('Choose four different ports between 1024 and 65535 in .env.')
    return values


def init():
    """One-shot root initialization; never reads the host's OpenClaw/OpenShell state."""
    _, _, gateway, health = ports()
    data = common.initialize()
    os.chown(data, UID, GID)
    os.chmod(data, 0o700)
    marker = GATEWAY_STATE / '.bac-gateway.json'
    GATEWAY_STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not marker.exists() and any(GATEWAY_STATE.iterdir()):
        raise RuntimeError('Refusing an existing, unmanaged /var/lib/bac-openshell directory.')
    if marker.exists() and common.read_json(marker).get('owner') != 'bac-demo':
        raise RuntimeError('Unexpected OpenShell data directory owner.')
    common.write_json(marker, {'owner': 'bac-demo', 'schema': 1})
    tls = GATEWAY_STATE / 'tls'
    subprocess.run(['/usr/local/bin/openshell-gateway', 'generate-certs', '--output-dir', str(tls),
                    '--server-san', 'host.openshell.internal'], check=True)
    CLIENT_CERTS.mkdir(parents=True, exist_ok=True)
    for name, source in [('ca.crt', tls/'ca.crt'), ('tls.crt', tls/'client/tls.crt'), ('tls.key', tls/'client/tls.key')]:
        destination = CLIENT_CERTS / name
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o600)
        os.chown(destination, UID, GID)
    os.chown(CLIENT_CERTS, UID, GID)
    os.chmod(CLIENT_CERTS, 0o700)
    images = common.read_json(LOCK_PATH)['images']
    # Host networking allows the driver to bind its dedicated Docker bridge callback.
    # TLS/JWT protect that callback; the operator endpoint is loopback only.
    config = f'''[openshell]
version = 2
[openshell.gateway]
bind_address = "127.0.0.1:{gateway}"
health_bind_address = "127.0.0.1:{health}"
compute_driver = "docker"
log_level = "info"
[openshell.gateway.mtls_auth]
enabled = true
[openshell.drivers.docker]
sandbox_label = "bac-demo"
default_image = "{images['openclaw']}"
supervisor_image = "{images['supervisor']}"
sandbox_runtime_image = "{images['sandbox']}"
image_pull_policy = "if_not_present"
# The OpenShell Docker supervisor uses host networking, so its gateway is the
# host loopback endpoint. A Docker-only hostname is not available there.
grpc_endpoint = "https://127.0.0.1:{gateway}"
'''
    target = GATEWAY_STATE / 'gateway.toml'
    target.write_text(config)
    os.chmod(target, 0o600)
    print('Multi-Agent Studio data and OpenShell certificates are ready.', flush=True)


def link_runtime(name):
    target = runtime.root() / name
    source = IMAGE_RUNTIME / name
    if target.is_symlink():
        if target.readlink() == source:
            return
        raise RuntimeError('Unexpected runtime link: ' + str(target))
    if target.exists():
        raise RuntimeError('This volume contains a host-installed runtime. Use a fresh Docker volume; do not mix installations.')
    target.symlink_to(source, target_is_directory=True)


def prepare():
    common.initialize()
    runtime.root().mkdir(parents=True, exist_ok=True)
    Path(os.environ['HOME']).mkdir(parents=True, exist_ok=True)
    lock = common.read_json(LOCK_PATH)
    for name in ('node', 'package'):
        link_runtime(name)
    plugin = IMAGE_RUNTIME / 'package/node_modules/@openclaw/openshell-sandbox'
    for package in (IMAGE_RUNTIME/'package/node_modules/openclaw', plugin):
        if common.read_json(package/'package.json')['version'] != runtime.VERSION:
            raise RuntimeError('Bundled OpenClaw/plugin version mismatch.')
    if lock['openclaw'] != runtime.VERSION:
        raise RuntimeError('Runtime lock and application versions disagree.')
    # CLI ssh-proxy resolves credentials by gateway name, including child processes.
    certs = Path(os.environ['XDG_CONFIG_HOME'])/'openshell/gateways/bac-demo/mtls'
    certs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('ca.crt', 'tls.crt', 'tls.key'):
        shutil.copyfile(CLIENT_CERTS/name, certs/name)
        os.chmod(certs/name, 0o600)
    endpoint = 'https://127.0.0.1:' + str(ports()[2])
    register_gateway(endpoint)
    from agent_policy import default_path, policy_document
    common.write_json(default_path(), policy_document())
    with runtime.config_lock():
        config = common.read_json(runtime.config_path()) or runtime.initial_config()
        config['gateway']['port'] = runtime.gateway_port()
        # Keep native diagnostics on the persistent volume across recreation.
        config.setdefault('logging', {})['file'] = str(runtime.root() / 'gateway-native.log')
        plugins = config.setdefault('plugins', {})
        plugins.setdefault('load', {})['paths'] = [str(plugin)]
        plugins.setdefault('entries', {})['openshell'] = {'enabled': True, 'config': {
            'command': str(Path(__file__).with_name('owned_openshell.py')), 'gateway': 'bac-demo', 'gatewayEndpoint': endpoint,
            'workspace': 'default', 'from': lock['images']['openclaw'], 'mode': 'mirror',
            'autoProviders': False, 'providers': [], 'policy': str(default_path())}}
        # OpenClaw 2026.11.3 keeps installation metadata outside openclaw.json.
        plugins.pop('installs', None)
        config['agents']['defaults']['sandbox'] = {'mode': 'off'}
        # Leases live in the app process, so persisted timers are never proof
        # that their owner is still connected after a crash/container restart.
        for agent_id, entry in config['agents']['entries'].items():
            if agent_id.startswith('bac-') and 'heartbeat' in entry:
                entry['heartbeat']['every'] = '0m'
        from research_search import configure
        configure(config, runtime.root())
        runtime.save_config(config)
    if 'bac-host' not in config['agents']['entries']:
        runtime.bootstrap_host()
    print(runtime.cli('config', 'validate'), flush=True)


def register_gateway(endpoint):
    command = ['/usr/local/bin/openshell', 'gateway']
    result = subprocess.run([*command, 'list', '--output', 'json'], check=True,
                            capture_output=True, text=True, timeout=15)
    entries = json.loads(result.stdout)
    if not isinstance(entries, list):
        raise RuntimeError('Unexpected OpenShell gateway list format.')
    current = next((item for item in entries if item.get('name') == 'bac-demo'), None)
    if current and current.get('endpoint') == endpoint:
        return
    if current:
        # Native gateway remove changes CLI registration only, retaining the service
        # and the mTLS directory (OpenShell 0.0.116 commands/gateway.rs).
        subprocess.run([*command, 'remove', 'bac-demo'], check=True, timeout=15)
    subprocess.run([*command, 'add', endpoint, '--name', 'bac-demo', '--local'], check=True, timeout=30)


def health():
    common.get_json('http://127.0.0.1:'+str(ports()[0])+'/health', timeout=2)
    runtime.gateway('/v1/models', timeout=2)
    openshell_health()


def openshell_health():
    result = subprocess.run(['/usr/local/bin/openshell', '--gateway', 'bac-demo',
                             'gateway', 'info', '--output', 'json'],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError('The dedicated OpenShell gateway is unavailable. Check docker compose logs openshell.')
    actual = json.loads(result.stdout).get('version', '')
    if actual.lstrip('v') != common.read_json(LOCK_PATH)['openshell']:
        raise RuntimeError('OpenShell gateway version does not match this release.')


def start_studio():
    command = [sys.executable, str(common.REPO/'scripts/serve.py'),
               '--host', '127.0.0.1', '--port', str(ports()[0])]
    return subprocess.Popen(command, start_new_session=True)


def serve():
    for port in ports()[:2]:
        with socket.socket() as probe:
            # A just-stopped HTTP server may leave TIME_WAIT sockets; that is
            # not another running service and must not stall an image update.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} is occupied. Choose a different Multi-Agent Studio port in .env; existing services were not stopped.') from None
    prepare()
    children = []
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([str(runtime.root()/'package/node_modules/.bin/openclaw'), 'gateway', 'run'],
                                        cwd=runtime.root(), env=runtime.environment(), start_new_session=True))
        deadline = time.monotonic() + 110
        while not stopping:
            if children[0].poll() is not None:
                raise RuntimeError('OpenClaw exited during startup. See its preceding log output.')
            try:
                runtime.gateway('/v1/models', timeout=2)
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise RuntimeError('OpenClaw did not become ready within 110 seconds.')
                time.sleep(1)
        if stopping:
            return
        children.append(start_studio())
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A studio process exited. Docker will restart the studio and its runtime together.')
            time.sleep(.5)
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        deadline = time.monotonic() + 25
        for child in children:
            try:
                child.wait(timeout=max(.1, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


def backup(directory=Path('/backup')):
    # Run only after Compose has stopped studio and openshell.
    common.require_idle()
    if not directory.is_dir():
        raise RuntimeError('Mount a backup directory at /backup.')
    destination = directory/('bac-'+time.strftime('%Y%m%d-%H%M%S')+'.tar.gz')
    temporary = destination.with_suffix('.partial')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output, tarfile.open(fileobj=output, mode='w:gz', dereference=False) as archive:
        # Skip the key store before tar descends into it, including interrupted key writes.
        for name, path in [('studio', common.home()), ('openshell', GATEWAY_STATE), ('client-certs', CLIENT_CERTS)]:
            archive.add(path, arcname=name, filter=lambda item: None if item.name == 'studio/credentials' else item)
    os.replace(temporary, destination)
    print('Saved '+str(destination))


if __name__ == '__main__':
    actions = {'init': init, 'serve': serve, 'health': health, 'backup': backup, 'idle': common.require_idle}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in actions:
            raise RuntimeError('Choose: init, serve, health, idle, backup')
        actions[sys.argv[1]]()
    except Exception as error:
        print('Multi-Agent Studio: '+str(error), file=sys.stderr, flush=True)
        sys.exit(1)
