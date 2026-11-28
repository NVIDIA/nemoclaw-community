# SPDX-License-Identifier: Apache-2.0

"""Publish and read the generated app bundle as one locked pair."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import tempfile


@contextlib.contextmanager
def bundle_lock(directory, exclusive=False):
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    with (directory / '.publish.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def _temporary(target, content):
    descriptor, name = tempfile.mkstemp(prefix='.' + target.name + '.', dir=target.parent)
    path = Path(name)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _restore(target, content):
    if content is None:
        target.unlink(missing_ok=True)
        return
    temporary = _temporary(target, content)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def publish(directory, page, build_info, replace=os.replace):
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    index = directory / 'index.html'
    version = directory / 'version.json'
    temporary_index = _temporary(index, page.encode('utf-8'))
    temporary_version = _temporary(version, (json.dumps(build_info) + '\n').encode('utf-8'))
    try:
        with bundle_lock(directory, exclusive=True):
            previous_index = index.read_bytes() if index.is_file() else None
            previous_version = version.read_bytes() if version.is_file() else None
            try:
                replace(temporary_index, index)
                replace(temporary_version, version)
            except Exception:
                _restore(index, previous_index)
                _restore(version, previous_version)
                raise
    finally:
        temporary_index.unlink(missing_ok=True)
        temporary_version.unlink(missing_ok=True)
