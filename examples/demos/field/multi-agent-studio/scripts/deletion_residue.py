# SPDX-License-Identifier: Apache-2.0

"""Permanent retirement of precisely marked native Trash copies.

The receipt survives crashes. Never select Trash by an agent name, age, or a
basename alone: a random marker written before native deletion proves ownership.
"""
import json
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import stat

MARKER = '.bac-deletion-owner.json'


class CleanupPrerequisiteError(RuntimeError):
    """Fixed operator guidance that is safe to show in the app."""


def require_staging_runtime(root):
    """Refuse before native deletion if the live gateway lacks this integration."""
    root = Path(root)
    if not (root/'package/node_modules/openclaw/package.json').exists():return
    digest = hashlib.sha256()
    for name in ('native_cleanup_loader.mjs', 'native_cleanup_trash.mjs', 'native_cleanup_tasks.mjs'):
        digest.update(Path(__file__).with_name(name).read_bytes())
    try:
        capability = json.loads((root/'cleanup-capability.json').read_text())
        if (not isinstance(capability, dict) or capability.get('version') != 1 or type(capability.get('pid')) is not int
                or capability['pid'] <= 0 or capability.get('integration') != digest.hexdigest()):
            raise ValueError('Stale native integration')
        os.kill(capability['pid'], 0)
    except (OSError, ValueError, TypeError):
        raise CleanupPrerequisiteError('Restart the studio and its managed agent runtime, then retry deletion. The runtime has not loaded the current cleanup support; no native files were removed.') from None


def atomic_json(path, value):
    path = Path(path)
    temporary = Path(str(path)+'.writing')
    fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError('Redirected cleanup write.')
            handle.truncate(0)
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)



def plain_directory(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise RuntimeError('Cleanup storage is redirected.')
    if not path.is_dir():raise RuntimeError('Cleanup storage is not a directory.')


def receipt_path(root, agent_id):
    from agent_identity import valid_agent_id
    if not valid_agent_id(agent_id):raise RuntimeError('Invalid cleanup identity.')
    return Path(root) / 'deletion-receipts' / (agent_id + '.json')


def prepare(root, agent_id, workspace):
    """Called only after quiescence and runtime ownership checks, before deletion."""
    root = Path(root).resolve()
    receipt = receipt_path(root, agent_id)
    receipt.parent.mkdir(mode=0o700, exist_ok=True)
    plain_directory(receipt.parent)
    paths = [Path(workspace).resolve(), root / 'state/agents' / agent_id / 'agent',
             root / 'state/agents' / agent_id / 'sessions']
    if receipt.is_symlink():raise RuntimeError('Cleanup receipt is redirected.')
    if receipt.exists():
        value = json.loads(receipt.read_text())
        if value.get('agentId') != agent_id or value.get('paths') != list(map(str, paths)):
            raise RuntimeError('Cleanup ownership changed.')
    else:
        value = {'agentId':agent_id, 'token':secrets.token_hex(32), 'paths':list(map(str, paths)), 'trash':[], 'marked':[], 'routed':[]}
        atomic_json(receipt, value)
    marker = {'agentId':agent_id, 'token':value['token']}
    for directory in paths:
        if not directory.exists() and not directory.is_symlink():continue
        plain_directory(directory)
        target = directory / MARKER
        if target.is_symlink():raise RuntimeError('Cleanup marker is redirected.')
        if target.exists() and json.loads(target.read_text()) != marker:
            raise RuntimeError('Cleanup marker ownership changed.')
        if str(directory) not in value['marked']:
            value['marked'].append(str(directory))
            atomic_json(receipt, value)
        atomic_json(target, marker)


def purge(root, agent_id, trash=None):
    """Run after native success and absent original paths, before dropping journal."""
    receipt = receipt_path(Path(root).resolve(), agent_id)
    if not receipt.exists():return
    plain_directory(receipt.parent)
    if receipt.is_symlink():raise RuntimeError('Cleanup receipt is redirected.')
    value = json.loads(receipt.read_text())
    if value.get('agentId') != agent_id:raise RuntimeError('Cleanup identity changed.')
    if any(Path(p).exists() or Path(p).is_symlink() for p in value['paths']):
        raise RuntimeError('Native files remain; permanent cleanup was postponed.')
    if not set(value.get('marked', [])) <= set(value.get('routed', [])):
        raise RuntimeError('The runtime has not enabled Multi-Agent Studio cleanup staging. Restart its service before retrying.')
    trash = Path(trash) if trash is not None else Path(root).resolve() / 'deletion-staging/.Trash'
    if not trash.exists() and not trash.is_symlink():return
    plain_directory(trash)
    for item in value['trash']:
        if (not isinstance(item, dict) or not isinstance(item.get('name'), str)
                or item['name'] in ('', '.', '..') or Path(item['name']).name != item['name']
                or type(item.get('dev')) is not int or type(item.get('ino')) is not int):
            raise RuntimeError('Invalid Trash receipt.')
        container = trash / item['name']
        try:info = container.lstat()
        except FileNotFoundError:continue
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino) != (item['dev'],item['ino']):
            raise RuntimeError('Trash item was replaced; cleanup was paused.')
        # Python uses descriptor-relative, symlink-resistant rmtree on supported
        # Mac/Linux hosts. Nested links are removed, never followed.
        if not shutil.rmtree.avoids_symlink_attacks:raise RuntimeError('Safe permanent cleanup is unavailable.')
        shutil.rmtree(container)


def forget_receipt(root, agent_id):
    receipt = receipt_path(Path(root).resolve(), agent_id)
    for path in (receipt, Path(str(receipt)+'.routing'), Path(str(receipt)+'.writing')):
        path.unlink(missing_ok=True)
    for directory in (Path(root).resolve()/'deletion-staging/.Trash', Path(root).resolve()/'deletion-staging'):
        try:directory.rmdir()
        except OSError:pass
    try:receipt.parent.rmdir()
    except OSError:pass


def skill_cache_path(root, agent_id, workspace):
    """Pinned 2026.11.3 shared.ts: agent scope plus canonical workspace hash."""
    from agent_identity import valid_agent_id
    if not valid_agent_id(agent_id):raise RuntimeError('Invalid cleanup identity.')
    scope = 'agent:' + agent_id + ':workspace:' + hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:32]
    slug = 'workspace-' + hashlib.sha256(scope.encode()).hexdigest()[:32]
    return Path(root).resolve() / 'state/sandbox/skills-workspaces' / slug


def purge_skill_cache(root, agent_id, workspace):
    """Remove only this identity's materialized skills, never prefix-match caches."""
    path = skill_cache_path(root, agent_id, workspace)
    if not path.exists() and not path.is_symlink():return
    plain_directory(path.parent)
    plain_directory(path)
    if not shutil.rmtree.avoids_symlink_attacks:raise RuntimeError('Safe cache cleanup is unavailable.')
    shutil.rmtree(path)
