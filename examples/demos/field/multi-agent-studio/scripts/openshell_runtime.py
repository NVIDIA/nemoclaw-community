# SPDX-License-Identifier: Apache-2.0

"""Use the release lock for native development as well as container deployments."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

import ops_common as common


def lock():
    return common.read_json(common.REPO / 'docker/runtime-lock.json')


def environment():
    result = dict(os.environ)
    config = common.home() / 'openclaw/openshell/config'
    if os.environ.get('BAC_CONTAINER') != '1' and config.is_dir():
        result['XDG_CONFIG_HOME'] = str(config)
    return result


def command():
    version = lock()['openshell']
    private = common.home() / 'openclaw/openshell' / version / 'bin/openshell'
    candidate = str(private) if private.is_file() else shutil.which('openshell')
    if not candidate:
        raise RuntimeError('Install the pinned OpenShell runtime with ./bac dev openshell enable.')
    result = subprocess.run([candidate, '--version'], capture_output=True, text=True, timeout=8)
    if result.returncode or result.stdout.strip() != 'openshell ' + version:
        raise RuntimeError('OpenShell ' + version + ' is required by this build. Run ./bac dev openshell enable; the protected request was not started.')
    return candidate


def install():
    """Install only the CLI, into app-owned data. Never replace a shared gateway."""
    try:
        return command()
    except RuntimeError:
        pass
    release = lock()
    system = {'Darwin': 'darwin', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
    spec = release.get('nativeDownloads', {}).get(system + '-' + arch if system and arch else '')
    if not spec:
        raise RuntimeError('No pinned OpenShell CLI is available for this platform.')
    destination = common.home() / 'openclaw/openshell' / release['openshell'] / 'bin'
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=destination) as folder:
        archive = Path(folder) / 'release.tar.gz'
        with urllib.request.urlopen(spec['url'], timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
            raise RuntimeError('OpenShell release checksum mismatch. The installed runtime was left unchanged.')
        with tarfile.open(archive) as tar:
            entries = [entry for entry in tar.getmembers() if entry.isfile() and Path(entry.name).name == 'openshell']
            if len(entries) != 1:
                raise RuntimeError('Unexpected OpenShell CLI archive.')
            binary = Path(folder) / 'openshell'
            binary.write_bytes(tar.extractfile(entries[0]).read())
            binary.chmod(0o755)
            os.replace(binary, destination / 'openshell')
    return command()
