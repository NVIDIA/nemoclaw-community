# SPDX-License-Identifier: Apache-2.0

"""Retire abandoned demo sessions and their explicitly owned native resources."""
import json
import logging
import re
import shutil
import time

SESSION_IDLE_SECONDS = 60 * 60


class SessionLifecycle:
    def initialize_session_lifecycle(self):
        with self.db() as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(participants)')}
            if 'last_seen' not in columns:
                db.execute('ALTER TABLE participants ADD COLUMN last_seen REAL NOT NULL DEFAULT 0')
            if 'retiring' not in columns:
                db.execute('ALTER TABLE participants ADD COLUMN retiring INTEGER NOT NULL DEFAULT 0')
            # Preserving restarts give saved browsers time to reconnect. An
            # already committed cleanup fence must survive every restart.
            db.execute('UPDATE participants SET last_seen=? WHERE retiring=0', (time.time(),))
            db.executescript('''
                CREATE TABLE IF NOT EXISTS session_cleanup (
                    participant TEXT PRIMARY KEY, next_attempt REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS session_cleanup_targets (
                    participant TEXT NOT NULL, native_id TEXT NOT NULL,
                    workspace_name TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(participant,native_id));
            ''')
        self.next_session_cleanup = 0

    def touch_session(self, participant):
        with self.db() as db:
            return bool(db.execute('UPDATE participants SET last_seen=? WHERE id=? AND retiring=0',
                                   (time.time(), participant)).rowcount)

    def retire_idle_sessions(self, now=None):
        """Fence expired accounts atomically with browser renewal and job claims."""
        now = time.time() if now is None else now
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            candidates = db.execute('SELECT id FROM participants WHERE retiring=0 AND last_seen<=?',
                                    (now - SESSION_IDLE_SECONDS,)).fetchall()
            for row in candidates:
                participant = row['id']
                owners = {r['id'] for r in db.execute('SELECT id FROM agents WHERE participant=?', (participant,))}
                # A long model call, policy update or final artifact write is
                # still real work even when its browser has gone away.
                with self.execution_lock:
                    executing = owners.intersection(self.executing_owners)
                if (executing
                        or db.execute("SELECT 1 FROM jobs WHERE owner IN (SELECT id FROM agents WHERE participant=?) AND status IN ('running','stopping')", (participant,)).fetchone()
                        or db.execute('SELECT 1 FROM agent_policies WHERE owner IN (SELECT id FROM agents WHERE participant=?) AND updating=1', (participant,)).fetchone()):
                    continue
                targets = []
                for agent in db.execute('SELECT id,profile FROM agents WHERE participant=? AND profile IS NOT NULL', (participant,)):
                    targets.append((json.loads(agent['profile'])['id'], agent['id']))
                targets += [(r['native_id'], r['workspace_name']) for r in db.execute(
                    'SELECT r.native_id,r.workspace_name FROM crew_resources r JOIN crew_contexts c ON c.owner=r.owner WHERE c.participant=?', (participant,))]
                db.executemany('INSERT OR IGNORE INTO session_cleanup_targets(participant,native_id,workspace_name) VALUES (?,?,?)',
                               [(participant, native, workspace) for native, workspace in targets])
                db.execute('UPDATE participants SET retiring=1 WHERE id=?', (participant,))
                # 3 is reserved for whole-session cleanup, independent of the
                # personal Delete agent queue (whose pending state is 2).
                db.execute('UPDATE agents SET deleting=3 WHERE participant=?', (participant,))
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE owner IN (SELECT id FROM agents WHERE participant=?) AND status IN ('queued','waiting')", (now, participant))
                db.execute('INSERT OR IGNORE INTO session_cleanup(participant) VALUES (?)', (participant,))

    def cleanup_session(self, participant):
        """Use the same native deletion safeguards as Delete agent, resumably."""
        from agent_identity import valid_agent_id
        with self.db() as db:
            if not db.execute('SELECT 1 FROM participants WHERE id=? AND retiring=1', (participant,)).fetchone():
                return
            targets = db.execute('SELECT * FROM session_cleanup_targets WHERE participant=? AND done=0', (participant,)).fetchall()
        plan = []
        for target in targets:
            if not valid_agent_id(target['native_id']) or not re.fullmatch(r'[a-f0-9]{24}(?:-[0-9]+)?', target['workspace_name']):
                raise RuntimeError('Invalid session cleanup ownership.')
            path = self.directory / 'workspaces' / target['workspace_name']
            if path.is_symlink() or path.parent.is_symlink():
                raise RuntimeError('Redirected session workspace; cleanup paused.')
            plan.append((target['native_id'], path))
        inspect = getattr(self.adapter, 'unregistered_deletion_targets', None)
        unused = set()
        if callable(inspect):
            # Native inspection validates one owner's ID family per call. A
            # browser may own several personal agents and two independent teams.
            families = {}
            for target in plan:
                families.setdefault(target[0][:28], []).append(target)
            for family in families.values():
                unused.update(inspect(family))
        for native, path in plan:
            if self.stop.is_set():
                return
            if native not in unused:
                self.adapter.remove(native, path)
            if path.exists():
                shutil.rmtree(path)
            finalize = getattr(self.adapter, 'finalize_removal', None)
            if callable(finalize) and native not in unused:
                finalize(native, path)
            self.provisioned.discard(native)
            with self.db() as db:
                db.execute('UPDATE session_cleanup_targets SET done=1 WHERE participant=? AND native_id=?', (participant, native))
        with self.db() as db:
            if db.execute('SELECT 1 FROM session_cleanup_targets WHERE participant=? AND done=0', (participant,)).fetchone():
                return
            owners = [r['id'] for r in db.execute('SELECT id FROM agents WHERE participant=?', (participant,))]
            for owner in owners:
                path = self.workspace(owner)
                if path.is_symlink() or path.parent.is_symlink():
                    raise RuntimeError('Redirected session workspace; cleanup paused.')
                if path.exists():
                    shutil.rmtree(path)
                db.execute('DELETE FROM survey_responses WHERE token IN (SELECT token FROM event_surveys WHERE owner=?)', (owner,))
                for table in ('event_surveys', 'jobs', 'agent_policies', 'heartbeat_controls', 'heartbeat_receipts', 'agent_deletions', 'crew_resources'):
                    db.execute('DELETE FROM '+table+' WHERE owner=?', (owner,))
                # All owner-specific metadata uses an exact colon-delimited ID.
                db.execute("DELETE FROM metadata WHERE key LIKE ? OR key LIKE ?", ('%:'+owner, '%:'+owner+':%'))
            db.execute("DELETE FROM metadata WHERE key LIKE ? OR key LIKE ?", ('%:'+participant, '%:'+participant+':%'))
            db.execute('DELETE FROM crew_contexts WHERE participant=?', (participant,))
            db.execute('DELETE FROM agents WHERE participant=?', (participant,))
            db.execute('DELETE FROM participants WHERE id=?', (participant,))
            db.execute('DELETE FROM session_cleanup_targets WHERE participant=?', (participant,))
            db.execute('DELETE FROM session_cleanup WHERE participant=?', (participant,))
        with self.heartbeat.lock:
            for owner in owners:
                self.heartbeat.statuses.pop(owner, None)
                self.protection_activity.forget(owner)
        with self.execution_lock:
            for native, _ in plan:
                self.agent_locks.pop(native, None)
        # A different browser may create its team concurrently. Remove only
        # these owners' entries, without replacing a shared dictionary snapshot.
        for key in list(self.crew_resources):
            if key[0] in owners:
                self.crew_resources.pop(key, None)
        logging.info('Retired an inactive demo session (%s owned workspaces)', len(owners))

    def clean_idle_sessions(self):
        now = time.time()
        if now < self.next_session_cleanup or not self.delete_lock.acquire(blocking=False):
            return
        self.next_session_cleanup = now + 30
        try:
            self.retire_idle_sessions(now)
            with self.db() as db:
                pending = db.execute('SELECT participant,attempts FROM session_cleanup WHERE next_attempt<=? ORDER BY next_attempt', (now,)).fetchall()
            for row in pending:
                if self.stop.is_set():
                    break
                try:
                    self.cleanup_session(row['participant'])
                except Exception as error:
                    self.diagnostics.emit('session.cleanup-failed', participant=row['participant'], error=error)
                    # Do not discard ownership after a partial native failure.
                    # Keep the account fenced and resume from completed targets.
                    logging.exception('Inactive demo session cleanup will retry')
                    with self.db() as db:
                        attempt = row['attempts'] + 1
                        db.execute('UPDATE session_cleanup SET attempts=?,next_attempt=? WHERE participant=?',
                                   (attempt, time.time() + min(300, 10 * 2 ** min(attempt, 5)), row['participant']))
        finally:
            self.delete_lock.release()
