# SPDX-License-Identifier: Apache-2.0

"""One browser session at a time, before a second UI can prepare native teams.

This is a demo admission rule, not authentication. Non-UI clients such as the
host's credential helper retain the existing cookie/origin/CSRF checks.
"""
import re
import threading
import time
from studio_sessions import SESSION_IDLE_SECONDS

BROWSER_GRACE_SECONDS = 90
IN_USE = 'Close the demo in the other browser, then try again.'
FINISHING = 'The other demo is finishing a task. Try again shortly.'


class BrowserAccess:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.Lock()
        self.owner = None
        self.views = {}
        self.closed_views = {}

    def busy(self):
        with self.studio.db() as db:
            owners = {row['id'] for row in db.execute('SELECT id FROM agents WHERE participant=?', (self.owner,))}
            with self.studio.execution_lock:
                if owners.intersection(self.studio.executing_owners):
                    return True
            if db.execute('SELECT 1 FROM agent_policies WHERE owner IN (SELECT id FROM agents WHERE participant=?) AND updating=1', (self.owner,)).fetchone():
                return True
            return bool(db.execute("""SELECT 1 FROM jobs WHERE owner IN
                (SELECT id FROM agents WHERE participant=?) AND
                (status IN ('running','stopping') OR (status='queued' AND due<=?)) LIMIT 1""",
                (self.owner, time.time())).fetchone())

    def session(self, token, view, create=False):
        from studio import Problem
        if not re.fullmatch(r'[a-f0-9]{48}', view):
            raise Problem('Refresh the page to reconnect to the demo.')
        # Serialize admission and account creation. Losing browsers must not
        # create even an empty participant or trigger Stage 3 preparation.
        with self.lock:
            now = time.monotonic()
            self.closed_views = {key:closed for key,closed in self.closed_views.items() if now-closed < SESSION_IDLE_SECONDS}
            if view in self.closed_views:
                raise Problem('This demo tab has closed. Refresh to open it again.', 410)
            self.views = {key:seen for key,seen in self.views.items() if now-seen < BROWSER_GRACE_SECONDS}
            with self.studio.db() as db:
                row = db.execute('SELECT * FROM participants WHERE token=?', (token,)).fetchone() if token else None
                if self.owner and not db.execute('SELECT 1 FROM participants WHERE id=? AND retiring=0', (self.owner,)).fetchone():
                    self.owner = None
                    self.views.clear()
            if self.owner and (not row or row['id'] != self.owner):
                if self.views:
                    raise Problem(IN_USE, 423)
                if self.busy():
                    raise Problem(FINISHING, 423)
            if create:
                account, new = self.studio.session(token)
            else:
                if not row or not self.studio.touch_session(row['id']):
                    raise Problem('Open the Multi-Agent Studio page to start a session.', 401)
                account, new = dict(row), False
            if self.owner != account['id']:
                self.views.clear()
            self.owner = account['id']
            self.views[view] = now
            return account, new

    def release(self, participant, view):
        with self.lock:
            if participant == self.owner:
                # A late pagehide from before a refresh must not release a new
                # tab or a different browser that has since opened the demo.
                if view in self.views:
                    self.closed_views[view] = time.monotonic()
                    self.views.pop(view)
