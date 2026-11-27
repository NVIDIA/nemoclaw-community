# SPDX-License-Identifier: Apache-2.0

"""Keep explicit, per-agent Markdown edits across workspace regeneration."""
import json
import os
from pathlib import Path
import tempfile

MARKER = '.bac-edited-documents.json'


def edited_paths(workspace):
    path = Path(workspace) / MARKER
    if path.is_symlink():
        raise ValueError('Linked document metadata is not supported.')
    if not path.exists():
        return set()
    if path.stat().st_size > 32000:
        raise ValueError('Invalid document metadata.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('Invalid document metadata.')
    return set(value)


def atomic_write(path, content):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.document-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def mark_edited(workspace, paths):
    previous = edited_paths(workspace)
    atomic_write(Path(workspace) / MARKER, json.dumps(sorted(previous | set(paths))).encode('utf-8'))
