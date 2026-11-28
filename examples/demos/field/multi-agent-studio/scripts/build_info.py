# SPDX-License-Identifier: Apache-2.0

"""Non-secret build identity, shared by Settings, health and startup logs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(root=ROOT):
    version_file = root / 'VERSION'
    override = os.environ.get('BAC_DEMO_VERSION', '').strip()
    release_override = override if re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', override) else ''
    version = release_override or (version_file.read_text().strip() if version_file.exists() else 'unversioned')
    info = {'version': version, 'commit': '', 'branch': '', 'modified': False}
    # Bundles carry their source identity without requiring Git on the demo host.
    source = root / 'source-version.json'
    if source.exists():
        saved = json.loads(source.read_text())
        info.update({key: saved.get(key, info[key]) for key in ('commit', 'branch', 'modified')})
    else:
        # A community checkout can contain many examples. Only report Git identity
        # when this example belongs to it, and scope changes to this directory.
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()
        try:
            git('ls-files', '--error-unmatch', '--', 'VERSION')
            info.update(commit=git('rev-parse', 'HEAD'), branch=git('branch', '--show-current'))
            changes = git('status', '--porcelain', '--untracked-files=normal', '--', '.', ':!app/index.html')
            info['modified'] = bool(changes)
        except (OSError, subprocess.CalledProcessError):
            pass
    lock = root / 'docker/runtime-lock.json'
    info['runtime'] = {key: value for key, value in json.loads(lock.read_text()).items()
                       if key in ('node', 'openclaw', 'openshell')} if lock.exists() else {}
    return info


def bump(part, root=ROOT):
    path = root / 'VERSION'
    value = path.read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('VERSION must contain major.minor.patch.')
    numbers = list(map(int, value.split('.')))
    index = {'major': 0, 'minor': 1, 'patch': 2}[part]
    numbers[index] += 1
    numbers[index + 1:] = [0] * (2 - index)
    value = f'{numbers[0]}.{numbers[1]}.{numbers[2]}'
    path.write_text(value + '\n')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('show', 'bump'), nargs='?', default='show')
    parser.add_argument('part', choices=('patch', 'minor', 'major'), nargs='?', default='patch')
    args = parser.parse_args()
    print(bump(args.part) if args.action == 'bump' else json.dumps(read()))
