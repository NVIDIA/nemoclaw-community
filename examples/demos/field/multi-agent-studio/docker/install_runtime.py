# SPDX-License-Identifier: Apache-2.0

"""Image-build helper: fetch only checksum-pinned Linux runtime archives."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request


def install(arch):
    lock = json.loads(Path(__file__).with_name('runtime-lock.json').read_text())
    if arch not in lock['downloads']:
        raise RuntimeError('Supported image architectures: amd64, arm64')
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        for component, spec in lock['downloads'][arch].items():
            archive = temp / (component + '.tar.gz')
            with urllib.request.urlopen(spec['url'], timeout=120) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
                raise RuntimeError(component + ' checksum mismatch')
            target = temp / component
            with tarfile.open(archive) as tar:
                tar.extractall(target, filter='data')
            if component == 'node':
                (Path('/opt/bac/runtime')).mkdir(parents=True, exist_ok=True)
                shutil.move(str(next(target.iterdir())), '/opt/bac/runtime/node')
            else:
                binaries = list(target.rglob('openshell'))
                if len(binaries) != 1 or not binaries[0].is_file():
                    raise RuntimeError('Unexpected OpenShell release archive')
                shutil.copy2(binaries[0], '/usr/local/bin/openshell')


if __name__ == '__main__':
    install(sys.argv[1])
