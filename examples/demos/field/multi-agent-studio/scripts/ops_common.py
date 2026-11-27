# SPDX-License-Identifier: Apache-2.0

"""Small standard-library helpers shared by the Spark management commands."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
MARKER = '.bac-managed.json'
UNIT_MARKER = '# Managed by bac-demo'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    os.replace(temporary, path)


def home():
    return Path(os.environ.get('BAC_DATA_DIR', str(Path.home() / '.local/share/bac-demo'))).expanduser().absolute()


def initialize():
    root = home()
    if root.is_symlink() or root.resolve() in (Path('/'), Path.home(), REPO):
        raise RuntimeError('BAC_DATA_DIR must be a dedicated, non-symlink directory outside the checkout.')
    if REPO == root.resolve() or REPO in root.resolve().parents:
        raise RuntimeError('Keep BAC_DATA_DIR outside the Git checkout.')
    if root.exists() and not (root / MARKER).exists() and any(root.iterdir()):
        raise RuntimeError('BAC_DATA_DIR is not an empty or managed directory: ' + str(root))
    root.mkdir(parents=True, exist_ok=True)
    if not (root / MARKER).exists():
        write_json(root / MARKER, {'owner': 'bac-demo', 'schema': 1})
    elif read_json(root / MARKER).get('owner') != 'bac-demo':
        raise RuntimeError('Unexpected data directory owner.')
    return root


@contextlib.contextmanager
def locked():
    root = initialize()
    with (root / '.operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another Multi-Agent Studio setup/update operation is running.')
        yield root


def owned_directory(path):
    root = home()
    if read_json(root / MARKER, {}).get('owner') != 'bac-demo':
        raise RuntimeError('Refusing changes outside a managed data directory.')
    if path == root or root.resolve() not in path.resolve().parents:
        raise RuntimeError('Path escapes the managed data directory: ' + str(path))
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise RuntimeError('Refusing a symlink in a managed directory: ' + str(parent))
    return path


def remove_directory(path):
    owned_directory(path)
    if path.exists():
        shutil.rmtree(path)


def systemd_available():
    if sys.platform != 'linux' or not shutil.which('systemctl'):
        return False
    result = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True)
    return result.returncode == 0


def require_systemd():
    if not systemd_available():
        raise RuntimeError('A Linux systemd user session is required. SSH into Spark as your normal user; do not run ./bac dev with sudo.')


def unit_path(name):
    if name not in ('bac-demo', 'bac-llm', 'bac-openclaw'):
        raise RuntimeError('Unknown service.')
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user' / (name + '.service')


def is_owned_unit(name):
    path = unit_path(name)
    return path.is_file() and not path.is_symlink() and path.read_text().startswith(UNIT_MARKER + '\n')


def active(name):
    if not systemd_available():
        return False
    return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', name], capture_output=True).returncode == 0


def service(name, action):
    require_systemd()
    if not is_owned_unit(name):
        raise RuntimeError('Refusing to control an absent or unmanaged service: ' + name)
    run(['systemctl', '--user', action, name])


def quote_unit(value):
    # Prefix ExecStart with ':' to disable environment substitution; escape specifiers.
    return json.dumps(str(value)).replace('%', '%%')


def service_environment():
    # A user service does not inherit the launching shell's tool locations.
    # Copy only non-secret paths, never API keys or the full shell environment.
    return {'BAC_DATA_DIR': str(home()), **{key: os.environ[key] for key in (
        'PATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'BAC_OPENCLAW_PORT'
    ) if key in os.environ}}


def install_unit(name, args, environment=None):
    require_systemd()
    path = unit_path(name)
    if (path.exists() or path.is_symlink()) and not is_owned_unit(name):
        raise RuntimeError('Refusing to overwrite an unmanaged unit: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    env = ''.join('Environment=' + quote_unit(k + '=' + str(v)) + '\n' for k, v in (environment or {}).items())
    content = (UNIT_MARKER + '\n[Unit]\nDescription=Multi-Agent Studio ' + name + '\n'
               '[Service]\nType=exec\n' + env + 'ExecStart=:' + ' '.join(map(quote_unit, args)) + '\n'
               'Restart=no\nTimeoutStopSec=60\nKillMode=control-group\n'
               '[Install]\nWantedBy=default.target\n')
    path.write_text(content)
    run(['systemctl', '--user', 'daemon-reload'])


def port_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def get_json(url, timeout=3):
    # Local readiness checks must not use an enterprise HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.load(response)


def require_idle():
    """Do not interrupt saved missions or a policy update during service changes."""
    database = home() / 'studio/studio.sqlite'
    if not database.exists():
        return
    with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        jobs = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','waiting','stopping')").fetchone()[0]
        policies = db.execute('SELECT count(*) FROM agent_policies WHERE updating=1').fetchone()[0]
    if jobs or policies:
        raise RuntimeError('Finish or stop pending missions and policy updates in the app before changing services. Nothing was restarted.')


def wait_ready(probe, label, wait=0, unit=None):
    """Bounded readiness checks, with useful progress and early service-failure exit."""
    deadline = time.monotonic() + wait
    next_notice = 0
    while True:
        try:
            probe()
            print(label + ' ready.', flush=True)
            return
        except (OSError, ValueError, RuntimeError):
            pass
        if unit and is_owned_unit(unit) and systemd_available():
            state = subprocess.run(['systemctl', '--user', 'show', unit, '--property=ActiveState', '--value'],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            if state in ('failed', 'inactive'):
                raise RuntimeError(label + ' service stopped. Inspect ./bac dev ' + ('llm' if unit == 'bac-llm' else 'runtime') + ' logs.')
        now = time.monotonic()
        if now >= deadline:
            raise RuntimeError(label + ' is not ready. Check ./bac dev ' + ('llm' if unit == 'bac-llm' else 'runtime') + ' logs, then retry the check. The service was not stopped.')
        if now >= next_notice:
            print('Waiting for ' + label + ' (' + str(round(deadline-now)) + 's remaining)…', flush=True)
            next_notice = now + 15
        time.sleep(min(2, deadline-now))
