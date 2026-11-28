# SPDX-License-Identifier: Apache-2.0

"""Short-lived visual evidence from native policy logs."""
from contextlib import contextmanager
from collections import deque
import hashlib
import threading
import time


class ProtectionActivity:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque(maxlen=128)
        self.watchers = {}

    def observe(self, owner, role, agent_id, logs, started, cancelled=None):
        now = time.time()
        with self.lock:
            if cancelled is not None and cancelled.is_set():return
            known = {e['id'] for e in self.events}
            for log in logs:
                stamp = log.get('time')
                # Allow subsecond host/sandbox clock skew; fingerprints still deduplicate reads.
                # Native policy decisions only. An allow is permission to connect,
                # not proof that the remote service returned a successful response.
                decision = ((log.get('action') == 'deny' and log.get('reason') in ('policy-denied', 'destination-blocked'))
                            or (log.get('action') == 'allow' and log.get('reason') is None))
                if (not decision or not log.get('host')
                        or not isinstance(stamp, (int, float)) or not started - 1 <= stamp <= now + 2):
                    continue
                if log['action'] == 'allow':
                    # Only website destinations belong in the external-world visual.
                    # Local runtime/health connections must not appear as web access.
                    from agent_policy import destination_permission
                    try:
                        destination_permission(log['host'])
                    except ValueError:
                        continue
                identity = hashlib.sha256((agent_id + ':' + str(log.get('fingerprint') or (stamp, log.get('host')))).encode()).hexdigest()[:24]
                if identity in known:
                    continue
                known.add(identity)
                self.events.append({'id':identity, 'owner':owner, 'role':role, 'host':log.get('host', ''),
                                    'time':stamp, 'observedAt':now, 'source':'OpenShell policy log', 'action':log['action'], 'reason':log.get('reason')})

    def forget(self, owner):
        with self.lock:
            self.events = deque((e for e in self.events if e['owner'] != owner), maxlen=128)
            for cancelled in self.watchers.pop(owner, {}):cancelled.set()

    def observe_active(self, owner, role, agent_id, logs):
        """Reuse live policy reads only inside this identity's current watch window."""
        with self.lock:
            windows = [(cancelled, started)
                       for cancelled, (watched_role, watched_agent, started)
                       in self.watchers.get(owner, {}).items()
                       if watched_role == role and watched_agent == agent_id]
        for cancelled, started in windows:
            self.observe(owner, role, agent_id, logs, started, cancelled)

    def snapshot(self, owners, crew_owner):
        now = time.time()
        with self.lock:
            return [dict(e) for e in self.events if now-e['observedAt'] < 30
                    and ((e['role'] is None and e['owner'] in owners)
                         or (e['role'] is not None and e['owner'] == crew_owner))]

    def denials_since(self, owner, role, started):
        """Current-turn policy evidence, independent of the brief visual lifetime."""
        with self.lock:
            return sorted({e['host'] for e in self.events
                           if e['owner'] == owner and e['role'] == role
                           and e['action'] == 'deny' and e.get('reason', 'policy-denied') == 'policy-denied' and e['time'] >= started})[:8]

    @contextmanager
    def watch(self, owner, role, agent_id, reader):
        started = time.time()
        finished = threading.Event()
        cancelled = threading.Event()
        with self.lock:self.watchers.setdefault(owner, {})[cancelled] = (role, agent_id, started)
        def read():
            try:
                self.observe(owner, role, agent_id, reader(agent_id), started, cancelled)
            except Exception:
                pass  # Missing evidence never produces a shield hit or fails the task.
        def sample():
            try:
                while not finished.wait(3):
                    if cancelled.is_set():return
                    read()
                read()
                for delay in (.75, 1.5):
                    if cancelled.wait(delay):return
                    read()
            finally:
                with self.lock:
                    watchers = self.watchers.get(owner)
                    if watchers is not None:
                        watchers.pop(cancelled, None)
                        if not watchers:self.watchers.pop(owner, None)
        threading.Thread(target=sample, daemon=True, name='bac-policy-observer').start()
        try:
            yield
        finally:
            finished.set()  # One final read; don't delay the model result or UI for native log I/O.
