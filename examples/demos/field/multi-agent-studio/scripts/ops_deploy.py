# SPDX-License-Identifier: Apache-2.0

"""Deploy application snapshots without changing the model service or cache."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import zipfile

import ops_common as c


def git(*args):
    return c.run(['git', '-C', c.REPO, *args], capture_output=True, text=True).stdout.strip()


def clean_checkout():
    if git('status', '--porcelain'):
        raise RuntimeError('Checkout has local changes. Commit or move them before updating; no changes were discarded.')


def release_target(name):
    link = c.home() / 'demo' / name
    if not link.is_symlink():
        if link.exists():
            raise RuntimeError('Expected a managed release link: ' + str(link))
        return None
    target = link.resolve(strict=True)
    releases = (c.home() / 'demo/releases').resolve()
    if target.parent != releases or not (target / '.bac-release.json').is_file():
        raise RuntimeError('Release link points outside the managed releases.')
    return target


def point(name, target):
    directory = c.home() / 'demo'
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / name
    temporary = directory / ('.' + name + '-new')
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, link)


def stage():
    clean_checkout()
    revision = git('rev-parse', 'HEAD')
    releases = c.owned_directory(c.home() / 'demo/releases')
    releases.mkdir(parents=True, exist_ok=True)
    destination = (releases / (revision[:12] + '-' + str(time.time_ns()))).resolve()
    destination.mkdir()
    try:
        with tempfile.TemporaryDirectory(dir=releases) as scratch:
            archive = Path(scratch) / 'source.zip'
            git('archive', '--format=zip', '--output=' + str(archive), revision)
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    relative = Path(member.filename)
                    if relative.is_absolute() or '..' in relative.parts or stat.S_ISLNK(member.external_attr >> 16):
                        raise RuntimeError('Release archive contains an unsafe path.')
                source.extractall(destination)
                # ZipFile drops Git executable bits. Keep entry points runnable in
                # deployed snapshots without restoring setuid/group-write flags.
                for member in source.infolist():
                    if not member.is_dir():
                        (destination / member.filename).chmod(0o755 if member.external_attr >> 16 & 0o111 else 0o644)
        c.write_json(destination / 'source-version.json', {'commit': revision,
                     'branch': git('branch', '--show-current'), 'modified': False})
        version_file = destination / 'VERSION'
        version = version_file.read_text().strip() if version_file.exists() else revision
        c.run([sys.executable, destination / 'scripts/build.py'],
              env={**os.environ, 'BAC_DEMO_VERSION': version}, cwd=destination)
        page = destination / 'app/index.html'
        if not page.exists() or 'id="bac-planner"' not in page.read_text():
            raise RuntimeError('New release did not produce the expected application.')
        c.write_json(destination / '.bac-release.json', {'commit': revision})
        return destination
    except BaseException:
        c.remove_directory(destination)
        raise


def settings():
    return c.read_json(c.home() / 'demo/settings.json', {'host': '127.0.0.1', 'port': 8080})


def wait_ready(target):
    wanted = c.read_json(target / '.bac-release.json')['commit']
    port = settings()['port']
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            result = c.get_json('http://127.0.0.1:' + str(port) + '/health', timeout=1)
            # Older snapshots reported their commit in the version field.
            revision = result.get('commit', result.get('version'))
            if result.get('app') == 'bac-demo' and revision == wanted:
                return
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError('New application version did not become healthy within 15 seconds.')


def activate(target, restart=False):
    old = release_target('current')
    point('current', target)
    try:
        if restart:
            c.service('bac-demo', 'restart')
            wait_ready(target)
    except BaseException:
        if old:
            point('current', old)
            try:
                c.service('bac-demo', 'restart')
                wait_ready(old)
            except Exception as recovery_error:
                print('Previous release restored on disk; restart needs attention:', recovery_error, file=sys.stderr)
        else:
            (c.home() / 'demo/current').unlink()
            c.service('bac-demo', 'stop')
        raise
    if old and old != target:
        point('previous', old)
    print('Application version:', c.read_json(target / '.bac-release.json')['commit'][:12])
    print('LLM runtime, model weights and bac-llm service were not changed.')


def update():
    clean_checkout()
    c.require_idle()
    if git('branch', '--show-current') != 'main':
        raise RuntimeError('Switch to main before updating this demo checkout.')
    git('fetch', 'origin', 'main')
    ahead = git('rev-list', '--count', 'origin/main..HEAD')
    if ahead != '0':
        raise RuntimeError('Local commits are ahead of or diverged from origin/main; resolve them before updating.')
    git('merge', '--ff-only', 'origin/main')
    current = release_target('current')
    if current and c.read_json(current / '.bac-release.json')['commit'] == git('rev-parse', 'HEAD'):
        print('Already on the latest application version. The previous release and model service are unchanged.')
        return
    target = stage()
    try:
        activate(target, restart=c.active('bac-demo'))
    except BaseException:
        print('Application activation failed; the previous release was restored when available.', file=sys.stderr)
        raise
    print('Refresh the browser to load the new UI. Agent identities, files, memory and jobs are preserved outside the release.')


def validate_start(host=None, port=None):
    c.require_systemd()
    current = release_target('current')
    new_settings = settings()
    if host is not None:
        new_settings['host'] = host
    if port is not None:
        new_settings['port'] = port
    running = c.active('bac-demo')
    if running and not c.is_owned_unit('bac-demo'):
        raise RuntimeError('Existing bac-demo service is not managed by this tool.')
    if (not running or new_settings['port'] != settings()['port']) and not c.port_free(new_settings['port']):
        raise RuntimeError('Application port is already used. Stop ./bac dev preview or choose --port 8081.')
    if not current:
        clean_checkout()
    return current, new_settings, running


def start(host=None, port=None):
    current, new_settings, running = validate_start(host, port)
    if running and current and new_settings == settings():
        wait_ready(current)
        print('Application already ready at http://127.0.0.1:' + str(new_settings['port']) + '. Existing connections kept.')
        return
    if running:
        c.require_idle()
    if not current:
        current = stage()
        activate(current)
    c.install_unit('bac-demo', [sys.executable, c.home() / 'demo/current/scripts/serve.py',
                              '--host', new_settings['host'], '--port', str(new_settings['port'])],
                   c.service_environment())
    c.write_json(c.home() / 'demo/settings.json', new_settings)
    c.service('bac-demo', 'enable')
    c.service('bac-demo', 'restart')
    wait_ready(current)
    print('Application ready at http://' + new_settings['host'] + ':' + str(new_settings['port']))


def rollback():
    previous = release_target('previous')
    if not previous:
        raise RuntimeError('There is no previous successful application release to restore.')
    c.require_idle()
    activate(previous, restart=c.active('bac-demo'))
    print('Application rolled back. The Git checkout remains on its current commit. Refresh the browser.')


def status():
    current = release_target('current')
    print('Application service:', 'running' if c.active('bac-demo') else 'stopped / not managed')
    print('Application release:', c.read_json(current / '.bac-release.json')['commit'][:12] if current else 'not deployed')
    print('OpenClaw service:', 'starting/running' if c.active('bac-openclaw') else 'stopped / not managed')
    print('Model service:', 'starting/running' if c.active('bac-llm') else 'stopped / not managed')
    print('Selected model:', c.read_json(c.home() / 'llm.json', {}).get('profile', 'none'))
    print('Persistent data:', c.home())
