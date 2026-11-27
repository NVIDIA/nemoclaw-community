# SPDX-License-Identifier: Apache-2.0

"""Read native OpenClaw heartbeat artifacts; never simulate a model response."""
import json
import math
from pathlib import Path
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import NamedTuple

import tech_radar
import model_connections
import personal_models


class RoomView(NamedTuple):
    revision: int
    open_task: bool
    priority: int
    changed: float


VIEW_STATES = ('hidden', 'visible', 'focused')


class RadarHeartbeat:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.RLock()
        # Every browser read renews its lease. Native timer/configuration I/O
        # can be slow and must not hold up those otherwise read-only requests.
        self.presence_lock = threading.RLock()
        self.statuses = {}
        self.clients = {}
        self.views = {}
        self.closed_clients = {}
        with studio.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS heartbeat_controls(owner TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS heartbeat_receipts(owner TEXT, event TEXT, job TEXT, PRIMARY KEY(owner,event));
            ''')

    def presence(self, participant, tab, end=False, open_task=None, revision=None, view_state=None):
        """Authenticated browser lease, independent of whether a model needs a key."""
        if not isinstance(tab, str) or not 1 <= len(tab) <= 100:
            return
        with self.presence_lock:
            now = time.monotonic()
            self.clients = {key: expiry for key, expiry in self.clients.items() if expiry > now}
            self.views = {key: view for key, view in self.views.items() if key in self.clients}
            self.closed_clients = {key: expiry for key, expiry in self.closed_clients.items() if expiry > now}
            key = (participant, tab)
            if end:
                self.clients.pop(key, None)
                self.views.pop(key, None)
                self.closed_clients[key] = now + 300
            elif key not in self.closed_clients:
                self.clients[key] = now + 90
                # Read-only renewals keep the current room. Delayed navigation
                # requests must not overwrite a more recent room transition.
                if type(open_task) is bool and type(revision) is int and 0 <= revision <= 2**53-1:
                    previous = self.views.get(key)
                    if previous is None or revision > previous.revision:
                        priority = VIEW_STATES.index(view_state) if view_state in VIEW_STATES else -1
                        self.views[key] = RoomView(revision, open_task, priority, now)

    def connected(self, participant):
        with self.presence_lock:
            return any(owner == participant and expiry > time.monotonic()
                       for (owner, tab), expiry in self.clients.items())

    def in_open_task(self, participant):
        with self.presence_lock:
            now = time.monotonic()
            live = [view for key, view in self.views.items()
                    if key[0] == participant and self.clients.get(key, 0) > now]
            # Polling an idle tab renews its lease, not its claim to be the current room.
            foreground = max(live, key=lambda view: (view.priority, view.changed), default=None)
            if foreground is not None and foreground.priority >= 0:
                return foreground.open_task
            return any(view.open_task for view in live)  # Older pages don't report focus.

    def disable(self, agent_id):
        toggle = getattr(self.studio.adapter, 'set_radar_heartbeat', None)
        if toggle:
            # Earlier ticks finish before the final disable; later ticks see
            # the committed deletion fence and cannot turn it back on.
            with self.lock:toggle(agent_id, False)

    def status(self, owner, profile):
        if 'radar' not in profile.get('skills', []):return None
        with self.studio.db() as db:
            row = db.execute('SELECT paused FROM heartbeat_controls WHERE owner=?', (owner,)).fetchone()
        return {'paused': bool(row and row['paused']), 'everySeconds': tech_radar.HEARTBEAT_SECONDS,
                **self.statuses.get(owner, {'state':'preparing'})}

    def control(self, owner, data):
        from studio import Problem
        if type(data.get('paused')) is not bool:raise Problem('Choose Pause or Resume.')
        with self.lock, self.studio.db() as db:
            self.studio.require_available(db, owner)
            profile = self.studio.profile(owner)
            if 'radar' not in profile.get('skills', []):raise Problem('This agent does not have Tech Radar.')
            # Stop new native runs before committing Pause. A running turn may finish.
            if data['paused']:self.disable(profile['id'])
            db.execute('INSERT OR REPLACE INTO heartbeat_controls VALUES (?,?)', (owner, int(data['paused'])))
            self.statuses[owner]={**self.statuses.get(owner,{}),'state':'paused' if data['paused'] else 'resuming'}
        return self.status(owner, profile)

    def import_events(self, owner):
        root = self.studio.workspace(owner).resolve()
        box = tech_radar.read(root, tech_radar.OUTBOX, {})
        if not isinstance(box, dict):raise ValueError('Invalid heartbeat output.')
        checked = box.get('checkedAt', 0)
        if isinstance(checked, (int,float)) and math.isfinite(checked):
            self.statuses[owner]['lastChecked'] = checked
        if box.get('status')=='source-unavailable':self.statuses[owner]['state']='source unavailable - check OpenShell Policy or connection'
        events = box.get('events', [])
        if not isinstance(events, list) or len(events)>50:raise ValueError('Invalid heartbeat output.')

        for event in events:
            if not isinstance(event,dict):continue
            token, answer, url, created = (event.get(k) for k in ('id','answer','url','created'))
            if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{64}',token):continue
            if not isinstance(answer,str) or not answer.strip() or len(answer)>1800:continue
            if not tech_radar.article_url(url):continue
            if type(created) not in (int,float) or not math.isfinite(created) or not 0<created<=time.time()+60:continue
            published=event.get('published')
            title=event.get('title')
            if type(published) not in (int,float) or not math.isfinite(published) or not 0<published<=time.time()+300:continue
            if not isinstance(title,str) or not 0<len(title)<=240:continue
            source={'url':url,'title':title,'published':datetime.fromtimestamp(published,timezone.utc).strftime('%Y-%m-%d'),'initial':event.get('initial') is True}
            job = secrets.token_hex(12)
            result = {'answer':answer, 'heartbeat':True, 'sources':[url], 'source':source}
            with self.studio.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT deleting,reset_at FROM agents WHERE id=?', (owner,)).fetchone()
                if not row or row['deleting'] or created < row['reset_at']:continue
                if db.execute('SELECT 1 FROM heartbeat_receipts WHERE owner=? AND event=?', (owner,token)).fetchone():continue
                db.execute('INSERT INTO heartbeat_receipts VALUES (?,?,?)', (owner,token,job))
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (job,owner,'heartbeat','done',json.dumps({'source':'OpenClaw heartbeat'}),json.dumps(result),'[]',created,time.time(),created))

    def notice(self, owner, code, message, created):
        """Operational notices are identified as app status, never agent prose."""
        previous=self.statuses[owner].get('noticeCode')
        if previous==code:return
        job=secrets.token_hex(12)
        with self.studio.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT deleting,reset_at FROM agents WHERE id=?',(owner,)).fetchone()
            if not row or row['deleting'] or created<row['reset_at']:return
            token='notice:'+code+':'+str(created)
            if db.execute('SELECT 1 FROM heartbeat_receipts WHERE owner=? AND event=?',(owner,token)).fetchone():return
            db.execute('INSERT INTO heartbeat_receipts VALUES (?,?,?)',(owner,token,job))
            result={'error':message,'systemNotice':True,'heartbeat':True}
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                (job,owner,'heartbeat','done','{}',json.dumps(result),'[]',created,time.time(),created))
        self.statuses[owner]['noticeCode']=code
        self.statuses[owner]['noticeAt']=created

    def observe_native(self, owner, profile):
        status=self.statuses[owner];now=time.time()
        if now-status.get('nativeCheckedAt',0)<10:return
        since=max(status.get('watchingSince',now),status.get('nativeCheckedAt',now-10)-1)
        status['nativeCheckedAt']=now
        reader=getattr(self.studio.adapter,'policy_events',None)
        if profile.get('protection')=='openshell' and callable(reader):
            try:logs=reader(profile['id'])
            except Exception:logs=[]
            self.studio.protection_activity.observe(owner,None,profile['id'],logs,since)
            denials=[e for e in logs if e.get('action')=='deny' and e.get('reason')=='policy-denied'
                     and isinstance(e.get('time'),(int,float)) and since-1<=e['time']<=now+2]
            if denials:
                self.notice(owner,'policy-denied','Heartbeat was blocked by OpenShell. Review the requested websites in OpenShell Policy.',max(e['time'] for e in denials))
                status['state']='needs website approval'
        failure_reader=getattr(self.studio.adapter,'heartbeat_failure',None)
        try:failure=failure_reader(profile['id'],status.get('watchingSince',now)) if callable(failure_reader) else None
        except Exception:failure=None
        if failure:
            self.notice(owner,failure['code'],failure['message'],failure['time'])
            status['state']='runtime command failed'
        if status.get('lastChecked',0)>status.get('noticeAt',now) and status['state']=='watching':
            status.pop('noticeCode',None)

    def tick(self):
        from studio import job_participants
        studio = self.studio
        toggle = getattr(studio.adapter, 'set_radar_heartbeat', None)
        if not toggle:return
        with studio.db() as db:
            agents = [dict(r) for r in db.execute('SELECT id,participant,profile,deleting FROM agents WHERE profile IS NOT NULL')]
        readiness = {}
        gateway_ready = False
        if any('radar' in json.loads(r['profile']).get('skills',[]) for r in agents):
            # Match Lounge provisioning, including host credentials and disabled
            # sources. The legacy session-only key can be absent while API is ready.
            readiness = studio.runtime_status()
            gateway_ready = bool(readiness.get('gateway'))
        for row in agents:
            owner=row['id']; profile=json.loads(row['profile'])
            if 'radar' not in profile.get('skills',[]):continue
            ready = personal_models.ready(profile, readiness)
            try:
                # Re-read under the same lock as Pause; a stale tick cannot re-enable it.
                with self.lock:
                    with studio.db() as db:
                        current = db.execute('SELECT profile,deleting FROM agents WHERE id=?',(owner,)).fetchone()
                        paused = db.execute('SELECT paused FROM heartbeat_controls WHERE owner=?',(owner,)).fetchone()
                        pending = db.execute("SELECT owner,kind,payload FROM jobs WHERE status IN ('queued','running','waiting','stopping')").fetchall()
                        preparations = db.execute("SELECT created,updated,status FROM jobs WHERE owner=? AND kind='prepare-agent' ORDER BY created DESC,rowid DESC LIMIT 3", (owner,)).fetchall()
                        busy = owner in studio.executing_owners or any(j['owner']==owner or any(m.get('key')==owner for m in job_participants(json.loads(j['payload']))) for j in pending)
                    if not current or current['profile'] != row['profile']:continue
                    paused = bool(paused and paused['paused'])
                    connected = self.connected(row['participant'])
                    room_paused = self.in_open_task(row['participant'])
                    preparation = preparations[0] if preparations else None
                    failures = 0
                    for attempt in preparations:
                        if attempt['status'] != 'error':break
                        failures += 1
                    retry_at = preparation['updated'] + min(60,15*2**(failures-1)) if failures else 0
                    if failures:
                        # Registration alone does not prove preparation succeeded;
                        # the policy/runtime check can still fail afterwards.
                        studio.provisioned.discard(profile['id'])
                    if connected and not room_paused and ready and gateway_ready and not current['deleting'] and not paused and not busy and model_connections.enabled():
                        old_route = studio.__dict__.get('_connection_routes',{}).get(profile['id'])
                        personal_models.prepare(studio, profile)
                        if old_route != studio._connection_routes.get(profile['id']):retry_at = 0
                    retrying = time.time() < retry_at
                    if connected and not room_paused and ready and gateway_ready and not current['deleting'] and not paused and not busy and not retrying and profile['id'] not in studio.provisioned:
                        with studio.db() as db:
                            db.execute('BEGIN IMMEDIATE')
                            live = db.execute('SELECT profile,deleting FROM agents WHERE id=?', (owner,)).fetchone()
                            if live and not live['deleting'] and live['profile'] == row['profile'] and not db.execute("SELECT 1 FROM jobs WHERE owner=? AND kind='prepare-agent' AND status IN ('queued','running')", (owner,)).fetchone():
                                studio.queue_agent_preparation(db, owner, profile)
                        studio.signal.set()
                    # Native scheduling can choose a near-immediate first tick.
                    # Keep the initial quiet period separate from the recurring cadence.
                    starting = bool(preparation and time.time() < preparation['created'] + tech_radar.STARTUP_DELAY_SECONDS)
                    enabled = bool(connected and not room_paused and ready and gateway_ready and not current['deleting'] and not paused and not busy and not starting and not retrying and profile['id'] in studio.provisioned)
                    registered = toggle(profile['id'],enabled) if gateway_ready else False
                    # Per-agent readiness also requires the gateway. Report its
                    # outage first instead of blaming a working model connection.
                    state = 'paused' if paused else 'paused in Open Task' if room_paused else 'waiting for browser' if not connected else 'waiting for runtime' if not gateway_ready else 'waiting for model' if not ready else 'waiting for task' if busy else 'retrying preparation' if retrying else 'starting soon' if starting and profile['id'] in studio.provisioned else 'watching' if enabled and registered else 'preparing'
                    # Native Heartbeat defers while its main request queue is busy,
                    # including work for a different agent. Keep its timer intact.
                    if state == 'watching' and any(j['kind'] in ('chat','crew','crew-chat') for j in pending):
                        state = 'waiting for other agents'
                    previous=self.statuses.get(owner,{})
                    since=previous.get('watchingSince',time.time()) if state == 'watching' else time.time()
                    self.statuses[owner] = {**previous, 'state':state, 'watchingSince':since}
                    if connected and not room_paused and not current['deleting'] and not paused:
                        self.import_events(owner)
                    if enabled and registered:self.observe_native(owner,profile)
                    last_check=max(since,self.statuses[owner].get('lastChecked',0))
                    if self.statuses[owner]['state']=='watching' and time.time()-last_check>100:
                        self.statuses[owner]['state']='check delayed'
            except Exception:
                with self.lock, studio.db() as db:
                    current=db.execute('SELECT deleting FROM agents WHERE id=?',(owner,)).fetchone()
                    if current and not current['deleting']:self.statuses[owner]={'state':'check failed'}
                    else:self.statuses.pop(owner,None)
                try:self.disable(profile['id'])
                except Exception:pass

    def work(self):
        try:
            while not self.studio.stop.is_set():
                try:self.tick()
                except Exception:pass  # Do not take down chat when a heartbeat artifact is malformed.
                self.studio.stop.wait(3)
        finally:
            with self.studio.db() as db:
                profiles=[json.loads(r['profile']) for r in db.execute('SELECT profile FROM agents WHERE profile IS NOT NULL')]
            for profile in profiles:
                if 'radar' in profile.get('skills',[]):
                    try:self.disable(profile['id'])
                    except Exception:pass
