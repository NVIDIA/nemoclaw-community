# SPDX-License-Identifier: Apache-2.0

"""Bounded, verified text handoffs from the current collaboration only."""
import hashlib
import json
import os
from pathlib import Path

TEXT_TYPES = {'.txt', '.md', '.json', '.csv', '.py', '.js', '.css'}
MAX_BYTES = 1024 * 1024
MAX_FILES = 12


def workspace_file_path(target, workspace=None):
    """Match native paths only inside this exact workspace, never by basename."""
    from studio import safe_file, Problem
    if not isinstance(target, str) or '\\' in target or '\x00' in target:
        return None
    path = Path(target)
    if '..' in path.parts:
        return None
    if workspace is not None:
        workspace = Path(workspace)
        if workspace.is_symlink():
            return None
    if path.is_absolute():
        if workspace is None:
            return None
        for root in (workspace.absolute(), workspace.resolve()):
            try:
                path = path.relative_to(root)
                break
            except ValueError:
                continue
        else:
            return None
    relative = path.as_posix()
    if workspace is not None:
        try:
            safe_file(workspace, relative, True)
        except (Problem, OSError, ValueError):
            return None
    return relative


def written_files(answer, required, *, workspace=None):
    """Current native write results can prove an idempotent save.

    Identical writes may preserve both the hash and mtime. Accept only declared
    outputs with a successful write in this invocation's transcript; collection
    still validates the actual file before exporting it. Reads and model claims
    alone never turn an old text file into a new handoff.
    """
    activity = getattr(answer, 'activity', None) or {}
    if activity.get('source') != 'OpenClaw transcript' or not activity.get('available'):
        return set()
    written = {workspace_file_path(call.get('target'), workspace) for call in activity.get('calls', [])
               if call.get('tool') == 'write' and call.get('status') == 'completed'}
    return {path for path in required if path in written and Path(path).suffix.lower() in TEXT_TYPES}


def reusable_code(studio, owner, job_id, agent, before, answer, required, *, source_workspace=None):
    """Recognize inspected, unchanged code from this agent's completed task.

    A model's path claim alone is insufficient. Require a successful read in
    this turn and a matching immutable export from this team's history since its last reset.
    This proves artifact provenance, not correctness for the new request; Casey
    still reviews the contribution against the current acceptance criteria.
    """
    from studio import safe_file, Problem
    from plan_revision import effective_outputs
    activity = getattr(answer, 'activity', None) or {}
    if activity.get('source') != 'OpenClaw transcript' or not activity.get('available'):
        return set()
    read = {workspace_file_path(call.get('target'), source_workspace) for call in activity.get('calls', [])
            if call.get('tool') == 'read' and call.get('status') == 'completed'}
    candidates = {p for p in required if p in before and p in read
                  and Path(p).suffix.lower() in {'.html', '.js', '.css', '.py'}}
    if not candidates:
        return set()
    with studio.db() as db:
        reset = studio.crew_chat_reset_state(db, owner)['at']
        rows = db.execute("SELECT payload FROM jobs WHERE owner=? AND kind='crew-chat' AND status='done' "
                          "AND created>=? AND created<(SELECT created FROM jobs WHERE id=?) "
                          "ORDER BY created DESC LIMIT 6", (owner, reset, job_id)).fetchall()
    verified = set()
    for row in rows:
        plan = json.loads(row['payload']).get('collaboration', {})
        if plan.get('outcome') != 'complete':
            continue
        for output in effective_outputs(plan).values():
            if output.get('agentId') != agent:
                continue
            for exported in output.get('files', []):
                source = plan.get('artifactSources', {}).get(exported)
                if source not in candidates:
                    continue
                try:
                    raw = safe_file(studio.workspace(owner), exported, True).read_bytes()
                    if hashlib.sha256(raw).hexdigest() == before[source][0]:
                        verified.add(source)
                except (Problem, OSError):
                    continue
    return verified


def snapshot_files(workspace):
    from studio import safe_file, Problem
    folder = workspace / 'artifacts'
    if folder.is_symlink() or not folder.is_dir():
        return {}
    found = {}
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(root) / d).is_symlink())
        for name in sorted(files):
            if Path(name).suffix.lower() not in TEXT_TYPES:
                continue
            relative = str((Path(root) / name).relative_to(workspace))
            try:
                path = safe_file(workspace, relative, True)
                if path.stat().st_size > MAX_BYTES:
                    continue
                raw = path.read_bytes()
                if not raw.decode('utf-8').strip():
                    continue
                found[relative] = (hashlib.sha256(raw).hexdigest(), path.stat().st_mtime_ns)
            except (Problem, OSError, UnicodeError):
                continue
    return found


def collect_files(studio, owner, job_id, role, before, source_map=None, *, source_workspace=None, written=()):
    from studio import safe_file, Problem
    workspace = source_workspace if source_workspace is not None else studio.workspace(owner, role)
    paths, total = [], 0
    for relative, signature in snapshot_files(workspace).items():
        if before.get(relative) == signature and relative not in written:
            continue
        try:
            raw = safe_file(workspace, relative, True).read_bytes()
            if hashlib.sha256(raw).hexdigest() != signature[0]:
                continue
            if len(paths) >= MAX_FILES or total + len(raw) > MAX_BYTES:
                raise RuntimeError('The contribution exceeds the handoff limit (12 text files / 1 MB). Split the task and retry.')
            target = ('artifacts/shared-' + job_id + '-r' + str(role) + '-' + signature[0][:12]
                      + '-' + str(len(paths)) + Path(relative).suffix.lower())
            safe_file(studio.workspace(owner), target).write_bytes(raw)
            if source_map is not None:
                source_map[target] = relative
            paths.append(target)
            total += len(raw)
        except (Problem, OSError):
            continue
    return paths
