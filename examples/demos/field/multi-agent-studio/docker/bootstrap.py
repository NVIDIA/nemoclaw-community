# SPDX-License-Identifier: Apache-2.0

"""Load a versioned app bundle without changing the dependency image."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

INPUTS = ('Dockerfile', 'docker/bootstrap.py', 'docker/install_runtime.py',
          'docker/runtime-lock.json', 'docker/runtime/package.json', 'docker/runtime/package-lock.json')
MANIFEST = Path('/opt/bac/build/runtime-manifest.json')
SOURCE = Path('/opt/bac/source')
APP = Path('/opt/bac/app')


def fingerprint(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in INPUTS}


def check(source=SOURCE, manifest=MANIFEST):
    expected = json.loads(manifest.read_text())
    if fingerprint(source) != expected:
        raise RuntimeError('App requires a different runtime image. Use the matching release image, or rebuild from source with ./bac start.')
    for name in ('scripts/container_runtime.py', 'scripts/build.py', 'src/studio.js', 'skills', 'scenario', 'VERSION', 'RELEASE_NOTES.md',
                 'runtime/research-guard/index.mjs', 'runtime/research-guard/openclaw.plugin.json'):
        if not (source / name).exists():
            raise RuntimeError('Incomplete app bundle: missing ' + name)


def stage(source=SOURCE, app=APP, manifest=MANIFEST):
    check(source, manifest)
    # Snapshot once per container start: patches never mix files in a running server.
    for name in ('scripts', 'src', 'skills', 'docker', 'runtime', 'scenario'):
        target = app / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source / name, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'node_modules'))
    shutil.copyfile(source / 'README.md', app / 'README.md')
    shutil.copyfile(source / 'VERSION', app / 'VERSION')
    shutil.copyfile(source / 'RELEASE_NOTES.md', app / 'RELEASE_NOTES.md')
    identity = source / 'source-version.json'
    if identity.is_file():
        shutil.copyfile(identity, app / identity.name)
    else:
        # A source checkout must not retain a previous release's commit identity.
        (app / identity.name).unlink(missing_ok=True)
    release = source / 'release.json'
    if release.exists():
        os.environ['BAC_DEMO_VERSION'] = json.loads(release.read_text())['version']
    subprocess.run([sys.executable, str(app / 'scripts/build.py')], check=True, cwd=app)


if __name__ == '__main__':
    try:
        command = sys.argv[1] if len(sys.argv) > 1 else 'serve'
        if command == '--stamp':
            MANIFEST.write_text(json.dumps(fingerprint(SOURCE), sort_keys=True))
        elif command == '--check':
            check()
            print('App bundle and runtime image match.')
        else:
            stage()
            os.chdir(APP)
            os.execv(sys.executable, [sys.executable, str(APP / 'scripts/container_runtime.py'), *sys.argv[1:]])
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print('Multi-Agent Studio: ' + str(exc), file=sys.stderr)
        sys.exit(1)
