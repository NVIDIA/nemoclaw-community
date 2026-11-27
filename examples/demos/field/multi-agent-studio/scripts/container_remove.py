# SPDX-License-Identifier: Apache-2.0

"""Remove only this distribution's Docker resources. Run by ./bac remove.

OpenShell labels: v0.0.116 crates/openshell-core/src/driver_utils.rs.
No prune, host installation removal, or model-server operations.
"""
import http.client
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
from urllib.parse import quote

PROJECT = 'bac-demo'
GATEWAY = Path('/var/lib/bac-openshell')
PROJECT_LABEL = 'com.docker.compose.project'
MANAGER = 'openshell.ai/managed-by'
NAMESPACE = 'openshell.ai/sandbox-namespace'
SERVICES = {'studio', 'openshell', 'init', 'sandbox-image'}
VOLUMES = {'bac-demo_studio-data': 'studio-data', 'bac-demo_client-certs': 'client-certs'}
IMAGE_HISTORY = '.bac-image-history.json'
STOPPED_SANDBOXES = '.bac-stopped-sandboxes.json'


def stopped_sandboxes(gateway):
    path = gateway / STOPPED_SANDBOXES
    if path.is_symlink():
        raise RuntimeError('Unexpected shutdown record symlink.')
    if not path.exists():
        return set()
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get('owner') != PROJECT or not isinstance(value.get('ids'), list)
            or any(not isinstance(i, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', i) for i in value['ids'])):
        raise RuntimeError('Invalid Multi-Agent Studio shutdown record.')
    return set(value['ids'])


def save_stopped_sandboxes(gateway, ids):
    path = gateway / STOPPED_SANDBOXES
    if path.is_symlink():
        raise RuntimeError('Unexpected shutdown record symlink.')
    temporary = gateway / (STOPPED_SANDBOXES + '.tmp-' + str(os.getpid()))
    with temporary.open('x') as stream:
        json.dump({'owner': PROJECT, 'ids': sorted(ids)}, stream)
    temporary.chmod(0o600)
    temporary.replace(path)


def image_history(gateway):
    path = gateway / IMAGE_HISTORY
    if path.is_symlink():
        raise RuntimeError('Unexpected image history symlink.')
    if not path.exists():
        return set()
    saved = json.loads(path.read_text())
    if not isinstance(saved, dict):
        raise RuntimeError('Invalid Multi-Agent Studio image history; nothing removed.')
    refs = saved.get('images')
    if (saved.get('owner') != PROJECT or saved.get('schema') != 1 or not isinstance(refs, list)
            or any(not isinstance(ref, str) or not re.fullmatch(r'[a-z0-9][a-z0-9./:_@-]+', ref) for ref in refs)):
        raise RuntimeError('Invalid Multi-Agent Studio image history; nothing removed.')
    return set(refs)


def record_images(lock, app_image, gateway=GATEWAY):
    marker = gateway_marker(gateway)
    refs = image_history(gateway)
    refs.add(app_image)
    refs.update(lock.get('images', {}).get(key) for key in ('gateway', 'supervisor', 'sandbox', 'openclaw'))
    refs.discard(None)
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9./:_@-]+', ref) for ref in refs):
        raise RuntimeError('Invalid image reference.')
    gateway.mkdir(parents=True, exist_ok=True)
    if not marker:
        (gateway / '.bac-gateway.json').write_text(json.dumps({'owner': PROJECT, 'schema': 1}))
    temporary = gateway / (IMAGE_HISTORY + '.tmp-' + str(os.getpid()))
    with temporary.open('x') as output:
        json.dump({'owner': PROJECT, 'schema': 1, 'images': sorted(refs)}, output)
    temporary.replace(gateway / IMAGE_HISTORY)


class DockerError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f'Docker {status}: {message}')


class Docker:
    def call(self, method, path):
        # Docker may use the full 45-second graceful-stop window before replying.
        connection = http.client.HTTPConnection('localhost', timeout=60)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(60)
        connection.sock.connect('/var/run/docker.sock')
        try:
            connection.request(method, '/v1.47' + path)
            response = connection.getresponse()
            raw = response.read()
            body = json.loads(raw) if raw else None
            if response.status >= 400:
                raise DockerError(response.status, (body or {}).get('message', 'request failed'))
            return body
        finally:
            connection.close()


def gateway_owns_sandbox(gateway, sandbox_id, sandbox_name):
    """Verify mountless OpenShell 0.1.4 containers against this gateway store."""
    database = gateway / 'gateway.db'
    if (database.is_symlink() or not database.is_file()
            or not isinstance(sandbox_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', sandbox_id)
            or not isinstance(sandbox_name, str) or not re.fullmatch(r'oc-[a-z0-9-]+', sandbox_name)):
        return False
    try:
        connection = sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True)
        try:
            return connection.execute(
                "SELECT 1 FROM objects WHERE id=? AND object_type='sandbox' AND name=?",
                (sandbox_id, sandbox_name)).fetchone() is not None
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def owned_container(container, gateway):
    labels = container.get('Labels') or {}
    if labels.get(PROJECT_LABEL) == PROJECT:
        if labels.get('com.docker.compose.service') not in SERVICES:
            raise RuntimeError('Unexpected service in the bac-demo project; nothing removed.')
        return True
    if labels.get(MANAGER) == 'openshell' and labels.get(NAMESPACE) == PROJECT:
        # A namespace match alone does not establish this gateway's ownership.
        mounted = any(m.get('Type') == 'bind' and m.get('Source', '').startswith(str(gateway) + '/')
                      for m in container.get('Mounts', []))
        if not mounted and not gateway_owns_sandbox(
                gateway, labels.get('openshell.ai/sandbox-id'), labels.get('openshell.ai/sandbox-name')):
            raise RuntimeError('A matching sandbox belongs to an unrecognized gateway; nothing removed.')
        return True
    return False


def check_foreign_mounts(containers, owned_ids, gateway, data_paths=()):
    for container in containers:
        if container['Id'] in owned_ids:
            continue
        for mount in container.get('Mounts', []):
            source = mount.get('Source', '')
            if (mount.get('Name') in VOLUMES or source == str(gateway)
                    or source.startswith(str(gateway) + '/')
                    or (source and any(source == str(path) or source.startswith(str(path) + '/')
                                       or str(path).startswith(source.rstrip('/') + '/') for path in data_paths))):
                raise RuntimeError('Another container uses Multi-Agent Studio data. Stop and disconnect it before removing Multi-Agent Studio.')


def project_data(installation, release=False):
    if installation is None:
        return []
    if installation.is_symlink() or not installation.is_dir():
        raise RuntimeError('Invalid Multi-Agent Studio installation directory.')
    if release:
        manifest = json.loads((installation / 'release.json').read_text())
        lock_hash = hashlib.sha256((installation / 'runtime-lock.json').read_bytes()).hexdigest()
        if ((installation / '.git').exists() or not manifest.get('version') or not manifest.get('image')
                or manifest.get('runtimeLockSHA256') != lock_hash):
            raise RuntimeError('Cannot verify this Multi-Agent Studio release folder; nothing removed.')
        paths = list(installation.iterdir())
    else:
        paths = [installation / name for name in ('shared', 'backups', '.env', 'api.json')]
    # Never traverse a symlink or a nested mounted filesystem during uninstall.
    for path in paths:
        if path.is_symlink() or not path.is_dir():
            continue
        for directory, _, _ in os.walk(path, followlinks=False):
            if Path(directory).is_mount():
                raise RuntimeError('A project data folder contains another mounted filesystem.')
    return paths


def delete_paths(paths):
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def gateway_marker(gateway):
    if gateway.is_symlink():
        raise RuntimeError('Refusing a symlink for the gateway directory.')
    if not gateway.exists() or not any(gateway.iterdir()):
        return None
    marker = gateway / '.bac-gateway.json'
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError('The gateway directory is not marked as Multi-Agent Studio-owned; nothing removed.')
    if json.loads(marker.read_text()) != {'owner': PROJECT, 'schema': 1}:
        raise RuntimeError('Unexpected gateway ownership marker; nothing removed.')
    return marker


def remove(docker, gateway=GATEWAY, lock=None, hostname=None, installation=None, host_installation=None, release=False):
    marker = gateway_marker(gateway)
    previous_images = image_history(gateway)
    data = project_data(installation, release=release)
    host_paths = ([Path(host_installation or installation)] if release else
                  [Path(host_installation or installation) / path.name for path in data])
    containers = docker.call('GET', '/containers/json?all=1')
    # Only our own helper may retain the gateway bind during cleanup. A label on
    # some other container must not exempt that container from the usage check.
    hostname = hostname or socket.gethostname()
    helper_ids = {c['Id'] for c in containers if c['Id'][:12] == hostname
                  and (c.get('Labels') or {}).get('com.nvidia.bac.cleanup') == 'true'}
    owned = [c for c in containers if c['Id'] not in helper_ids and owned_container(c, gateway)]
    ids = {c['Id'] for c in owned}
    check_foreign_mounts(containers, ids | helper_ids, gateway, host_paths)
    if not marker and any((c.get('Labels') or {}).get(NAMESPACE) == PROJECT for c in owned):
        raise RuntimeError('Cannot verify sandbox ownership without the Multi-Agent Studio gateway marker.')
    volumes = []
    for volume in docker.call('GET', '/volumes').get('Volumes') or []:
        name = volume['Name']
        if name not in VOLUMES:
            continue
        labels = volume.get('Labels') or {}
        if labels.get(PROJECT_LABEL) != PROJECT or labels.get('com.docker.compose.volume') != VOLUMES[name]:
            raise RuntimeError('A volume with a Multi-Agent Studio name has different ownership; nothing removed.')
        volumes.append(name)
    networks = []
    for network in docker.call('GET', '/networks'):
        labels = network.get('Labels') or {}
        if labels.get(PROJECT_LABEL) == PROJECT or (marker and network['Name'] == 'bac-sandboxes' and labels.get(MANAGER) == 'openshell'):
            detail = docker.call('GET', '/networks/' + network['Id'])
            if set((detail.get('Containers') or {})) - ids:
                raise RuntimeError('Another container uses the Multi-Agent Studio network; nothing removed.')
            networks.append(network['Id'])
    # Stop the app and gateway first, so they cannot provision new sandboxes.
    owned.sort(key=lambda c: 0 if (c.get('Labels') or {}).get('com.docker.compose.service') in ('studio', 'openshell') else 1)
    for container in owned:
        path = '/containers/' + container['Id']
        if container.get('State') == 'running':
            docker.call('POST', path + '/stop?t=25')
        docker.call('DELETE', path + '?v=true')
    for network in networks:
        docker.call('DELETE', '/networks/' + network)
    for name in volumes:
        docker.call('DELETE', '/volumes/' + quote(name, safe=''))
    # Recheck before deleting bind-mounted state. Retain marker on partial failure.
    check_foreign_mounts(docker.call('GET', '/containers/json?all=1'), helper_ids, gateway, host_paths)
    # Clear user data first; on a partial failure keep the launcher/manifest so
    # uninstall can be retried from this installation.
    retry_files = {'bac', 'remove.py', 'compose.yaml', '.env', 'runtime-lock.json', 'release.json', 'SHA256SUMS', 'image-archive.txt'}
    data.sort(key=lambda path: 0 if path.name in ('shared', 'backups') else 2 if path.name in retry_files else 1)
    if marker:
        for child in gateway.iterdir():
            if child == marker:
                continue
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                if child.is_mount():
                    raise RuntimeError('Unexpected nested mount in gateway state; cleanup paused.')
                shutil.rmtree(child)
        marker.unlink()
    print(f'Removed {len(owned)} Multi-Agent Studio containers and {len(volumes)} data volumes.', flush=True)
    # The launcher removes images after this helper exits, never with --force.
    images = docker.call('GET', '/images/json?all=1')
    refs = previous_images | {ref for key, ref in (lock or {}).get('images', {}).items()
                              if key in ('gateway', 'supervisor', 'sandbox', 'openclaw')}
    refs.update(c['Image'] for c in owned if c.get('Image'))
    for image in images:
        labels = image.get('Labels') or {}
        candidates = set((image.get('RepoTags') or []) + (image.get('RepoDigests') or [])) - {'<none>:<none>', '<none>@<none>'}
        app_refs = {ref for ref in candidates if ref.partition('@')[0].partition(':')[0]
                    in ('bac-studio', 'bac-studio-tests')}
        refs.update(app_refs)
        # An unrelated tag can share the same layers. Remove an ID only when
        # every reference belongs to Multi-Agent Studio, or an owned image is already dangling.
        if candidates == app_refs and (app_refs or labels.get('com.nvidia.bac.component') == 'studio'):
            refs.add(image['Id'])
    delete_paths(data)
    for ref in sorted(refs):
        print('BAC_IMAGE ' + ref)


def fresh(docker, gateway=GATEWAY, hostname=None):
    """Remove this installation's runtime state while preserving images and project files."""
    marker = gateway_marker(gateway)
    containers = docker.call('GET', '/containers/json?all=1')
    hostname = hostname or socket.gethostname()
    helper_ids = {c['Id'] for c in containers if c['Id'][:12] == hostname
                  and (c.get('Labels') or {}).get('com.nvidia.bac.cleanup') == 'true'}
    owned = [c for c in containers if c['Id'] not in helper_ids and owned_container(c, gateway)]
    ids = {c['Id'] for c in owned}
    check_foreign_mounts(containers, ids | helper_ids, gateway)
    if not marker and any((c.get('Labels') or {}).get(NAMESPACE) == PROJECT for c in owned):
        raise RuntimeError('Cannot verify sandbox ownership without the Multi-Agent Studio gateway marker.')
    volumes = []
    for volume in docker.call('GET', '/volumes').get('Volumes') or []:
        name = volume['Name']
        if name not in VOLUMES:
            continue
        labels = volume.get('Labels') or {}
        if labels.get(PROJECT_LABEL) != PROJECT or labels.get('com.docker.compose.volume') != VOLUMES[name]:
            raise RuntimeError('A volume with a Multi-Agent Studio name has different ownership; nothing reset.')
        volumes.append(name)
    networks = []
    for network in docker.call('GET', '/networks'):
        labels = network.get('Labels') or {}
        if labels.get(PROJECT_LABEL) == PROJECT or (marker and network['Name'] == 'bac-sandboxes' and labels.get(MANAGER) == 'openshell'):
            detail = docker.call('GET', '/networks/' + network['Id'])
            if set((detail.get('Containers') or {})) - ids:
                raise RuntimeError('Another container uses the Multi-Agent Studio network; nothing reset.')
            networks.append(network['Id'])
    owned.sort(key=lambda c: 0 if (c.get('Labels') or {}).get('com.docker.compose.service') in ('studio', 'openshell') else 1)
    for container in owned:
        path = '/containers/' + container['Id']
        name=(container.get('Names') or [container['Id'][:12]])[0].lstrip('/')
        print('Clearing container ' + name + '…', flush=True)
        if container.get('State') == 'running':
            docker.call('POST', path + '/stop?t=25')
        docker.call('DELETE', path + '?v=true')
    for network in networks:
        docker.call('DELETE', '/networks/' + network)
    for name in volumes:
        docker.call('DELETE', '/volumes/' + quote(name, safe=''))
    check_foreign_mounts(docker.call('GET', '/containers/json?all=1'), helper_ids, gateway)
    if marker:
        keep={marker,gateway/IMAGE_HISTORY}
        for child in gateway.iterdir():
            if child in keep:
                continue
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                if child.is_mount():
                    raise RuntimeError('Unexpected nested mount in gateway state; fresh start paused.')
                shutil.rmtree(child)
    print(f'Cleared Multi-Agent Studio runtime state, {len(owned)} containers and {len(volumes)} data volumes.', flush=True)


def stop(docker, gateway=GATEWAY, hostname=None):
    """Stop only verified Multi-Agent Studio resources, preserving containers and data."""
    marker = gateway_marker(gateway)
    containers = docker.call('GET', '/containers/json?all=1')
    hostname = hostname or socket.gethostname()
    helper_ids = {c['Id'] for c in containers if c['Id'][:12] == hostname
                  and (c.get('Labels') or {}).get('com.nvidia.bac.cleanup') == 'true'}
    owned = [c for c in containers if c['Id'] not in helper_ids and owned_container(c, gateway)]
    if owned and not marker:
        raise RuntimeError('Cannot verify Multi-Agent Studio ownership without the gateway marker.')
    # Record before stopping so an interrupted shutdown can be resumed safely.
    ids = stopped_sandboxes(gateway)
    ids.update(c['Id'] for c in owned if (c.get('Labels') or {}).get(MANAGER) == 'openshell'
               and c.get('State') in ('running', 'restarting', 'paused'))
    if ids:
        save_stopped_sandboxes(gateway, ids)
    # Resolve every ownership check before any action. Shut off provisioning first.
    owned.sort(key=lambda c: 0 if (c.get('Labels') or {}).get(PROJECT_LABEL) == PROJECT else 1)
    failures = []
    for container in owned:
        if container.get('State') not in ('running', 'restarting', 'paused'):
            continue
        try:
            docker.call('POST', '/containers/' + container['Id'] + '/stop?t=45')
        except DockerError as error:
            if error.status not in (304, 404):
                failures.append(container['Id'][:12])
        except OSError:
            failures.append(container['Id'][:12])
    if failures:
        raise RuntimeError('Could not confirm shutdown of Multi-Agent Studio containers: ' + ', '.join(failures)
                           + '. Other containers were attempted; saved data and the resume record are kept. Retry ./bac stop --keep-data.')
    print('Verified Multi-Agent Studio containers stopped; files, images and volumes are preserved.', flush=True)


def resume(docker, gateway=GATEWAY):
    """Resume only the sandboxes recorded by this shutdown command."""
    ids = stopped_sandboxes(gateway)
    if not ids:
        return
    if not gateway_marker(gateway):
        raise RuntimeError('Cannot verify Multi-Agent Studio ownership before resuming sandboxes.')
    containers = docker.call('GET', '/containers/json?all=1')
    selected = [c for c in containers if c['Id'] in ids]
    if any(not owned_container(c, gateway) or (c.get('Labels') or {}).get(MANAGER) != 'openshell' for c in selected):
        raise RuntimeError('A recorded sandbox no longer belongs to Multi-Agent Studio; nothing resumed.')
    for container in selected:
        if container.get('State') == 'running':
            continue
        try:
            docker.call('POST', '/containers/' + container['Id'] + '/start')
        except DockerError as error:
            if error.status not in (304, 404):
                raise
    (gateway / STOPPED_SANDBOXES).unlink()
    print('Previously stopped Multi-Agent Studio sandboxes resumed.', flush=True)


if __name__ == '__main__':
    try:
        if sys.argv[1] == '--stop':
            stop(Docker())
        elif sys.argv[1] == '--resume':
            resume(Docker())
        elif sys.argv[1] == '--fresh':
            fresh(Docker())
        elif sys.argv[1] == '--record':
            record_images(json.loads(Path(sys.argv[2]).read_text()), sys.argv[3])
        else:
            remove(Docker(), lock=json.loads(Path(sys.argv[1]).read_text()),
                   installation=Path(sys.argv[2]) if len(sys.argv) > 2 else None,
                   host_installation=sys.argv[3] if len(sys.argv) > 3 else None,
                   release=len(sys.argv) > 4 and sys.argv[4] == 'release')
    except (RuntimeError, OSError, ValueError) as error:
        print('Multi-Agent Studio resource operation stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
