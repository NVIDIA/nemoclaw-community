# SPDX-License-Identifier: Apache-2.0

"""Durable participant workspaces and bounded OpenClaw task queues.

This is a trusted workshop LAN application, not a public multi-tenant service.
Every browser gets an opaque, HttpOnly session; no gateway credentials reach it.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time

import agent_runtime as runtime
import ops_common as c
from agent_reply import without_reply_prefix
from studio_policy import PolicyControls
from crew_roundtable import RoundtableControls, participants as job_participants
from crew_ownership import CrewOwnership
from studio_sessions import SessionLifecycle
from collaboration_plan import CollaborationPlans, is_plan, missing_skill_hints, plan_output_reason, plan_task, unassigned_team_message
from webpage_artifacts import DEMO_CODING_INSTRUCTIONS, PAGE_INSTRUCTIONS, html_files, collect_pages
from role_boundaries import implementation_scope, scope_contract

CREW_CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'src/crew-catalog.json').read_text())
ROLES = [(member['name'], member['role'], member['persona']) for member in CREW_CATALOG]
# Stable slot IDs keep existing Open Task histories and native identities intact.
ACTIVE_ROLES = tuple(i for i,m in enumerate(CREW_CATALOG) if not m.get('retired'))
ACTIVE = ('queued', 'running', 'waiting', 'stopping')
ROLE_SKILLS = [list(member['skills']) for member in CREW_CATALOG]
MAX_AGENTS = 12
ROLE_AVATARS = [dict(body=b, color=c, accessory=a) for b, c, a in (
    ('classic', 'green', 'pirate'), ('round', 'cyan', 'headset'), ('rover', 'amber', 'cap'),
    ('round', 'coral', 'antenna'), ('classic', 'violet', 'glasses'), ('claw', 'ice', 'headset'), ('classic', 'cyan', 'glasses'), ('round', 'violet', 'cap'), ('rover', 'cyan', 'glasses'), ('classic', 'green', 'headset'))]
AVATAR_CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'src/avatar-catalog.json').read_text())
AVATAR_OPTIONS = {'body': tuple(body['id'] for body in AVATAR_CATALOG['bodies']) + tuple(AVATAR_CATALOG['legacyBodies']),
                  'color': ('green', 'cyan', 'amber', 'coral', 'violet', 'ice') + tuple(AVATAR_CATALOG['palettes']),
                  'accessory': tuple(AVATAR_CATALOG['accessories'])}
LEGACY_AVATAR_DEFAULTS = {'body': ('classic', 'round', 'rover', 'cat', 'claw', 'crab'),
                          'color': ('green', 'cyan', 'amber', 'coral', 'violet', 'ice'),
                          'accessory': ('antenna', 'headset', 'glasses', 'cap')}


def personal_agent_activity(jobs, owner):
    """Display actual personal work separately from reservations for a Multi-Agent Studio run."""
    activities = []
    for job in jobs:
        payload, kind = job['payload'], job['kind']
        # Background readiness keeps its reservation but is not personal work.
        if kind in ('prepare', 'prepare-agent') or (kind == 'crew-chat' and not payload.get('roundtable') and not payload.get('collaboration')):
            continue
        if payload.get('reactionRetry') and payload['reactionRetry'] != owner:
            continue
        roster_member = not payload.get('reactionRetry') and any(m.get('key') == owner for m in payload.get('roster', []))
        if payload.get('collaboration') and roster_member:
            bindings = payload['collaboration'].get('visitorBindings', {})
            active = bindings.get(str(payload['collaboration'].get('activeRole')), {}).get('key') == owner
            activities.append({'kind': 'mission', 'label': 'Working with Casey' if active else 'Waiting for Casey',
                               'job': job['id'], 'status': job['status']})
            continue
        guest = any(m.get('key') == owner for m in payload.get('roundtable', {}).get('members', []))
        if kind in ('crew','crew-chat') and not roster_member:
            reply = payload.get('roundtable', {}).get('replies', {}).get(owner, {})
            if not guest or reply.get('status') in ('done', 'error', 'cancelled'):
                continue
            category, label = 'roundtable', 'Sharing opinion' if reply.get('status') == 'running' else 'Waiting for task results' if payload.get('collaboration') else 'Waiting for event results'
        elif job['owner'] == owner or roster_member:
            category = 'mission'
            label = {'queued':'Request queued', 'running':'Working on your request',
                     'waiting':'Awaiting your decision', 'stopping':'Stopping request'}[job['status']]
            if kind == 'reminder' and job['status'] == 'queued' and job['due'] > time.time():
                label = 'Follow-up scheduled'
        else:
            continue
        activities.append({'kind':category, 'label':label, 'job':job['id'], 'status':job['status']})
    return min(activities, key=lambda a: {'mission':0, 'roundtable':1}[a['kind']]) if activities else None


def avatar_for(owner, avatar=None):
    """Stable defaults also give legacy agents a persistent visual identity."""
    seed = int(hashlib.sha256(owner.encode()).hexdigest()[:8], 16)
    defaults = {key: values[(seed // (7 ** i)) % len(values)]
                for i, (key, values) in enumerate(LEGACY_AVATAR_DEFAULTS.items())}
    if avatar is None:
        return defaults
    if not isinstance(avatar, dict) or set(avatar) != set(AVATAR_OPTIONS):
        raise Problem('Choose a body, color and accessory for your agent.')
    if avatar.get('body') == 'fox':
        avatar = {**avatar, 'body': 'claw'}
    if any(not isinstance(avatar[key], str) or avatar[key] not in options for key, options in AVATAR_OPTIONS.items()):
        raise Problem('Choose an available agent appearance.')
    return dict(avatar)


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(value, limit=6000, name='Text'):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise Problem(name + ' is missing or too long.')
    return value.strip()


def safe_file(directory, relative, exists=False):
    if not isinstance(relative, str) or not re.fullmatch(r'[\w. ()/-]{1,160}', relative):
        raise Problem('Invalid file name.')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or path.suffix.lower() not in ('.md', '.txt', '.csv', '.html', '.json', '.xlsx', '.eml', '.pdf', '.pptx', '.png', '.jpg', '.webp', '.py', '.js', '.css'):
        raise Problem('Use a supported document, spreadsheet or email draft in this workspace.')
    result = directory / path
    if directory.resolve() not in result.resolve().parents:
        raise Problem('File is outside this workspace.')
    for part in (result, *result.parents):
        if part == directory:
            break
        if part.is_symlink():
            raise Problem('Symbolic links are not accepted.')
    from document_upload import MAX_FILE
    if exists and (not result.is_file() or result.stat().st_size > MAX_FILE):
        raise Problem('File is unavailable or exceeds 10 MB.', 404)
    return result


class ActiveTeamCall:
    """Send Stop off the request thread, only while this exact call owns its session."""
    def __init__(self, abort, agent_id, session):
        self.abort = abort
        self.agent_id = agent_id
        self.session = session
        self.stop_requested = threading.Event()
        self.finished = threading.Event()
        self.worker = None

    def request_stop(self):
        # Caller holds the Studio execution lock.
        if self.worker is None:
            self.stop_requested.set()
            self.worker = threading.Thread(target=self._interrupt, daemon=True)
            self.worker.start()

    def _interrupt(self):
        # Registration may lag the request. Fall back to the normal worker
        # drain if the gateway remains unavailable across these attempts.
        for delay in (0, 0.25, 1, 2, 4, 8):
            if self.finished.wait(delay) or self.abort(self.agent_id, self.session):
                break


class Studio(CollaborationPlans, CrewOwnership, SessionLifecycle, PolicyControls, RoundtableControls):
    def __init__(self, directory=None, adapter=runtime, start_worker=True, recover=False):
        self.directory = Path(directory) if directory else c.initialize() / 'studio'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.instance_lock = None
        if start_worker:
            self.instance_lock = (self.directory / '.server.lock').open('a')
            try:
                fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.instance_lock.close()
                raise RuntimeError('Another Multi-Agent Studio app is already using this data directory. Stop it before starting a second server.')
        from diagnostics import Diagnostics
        self.diagnostics = Diagnostics(self.directory)
        self.db_path = self.directory / 'studio.sqlite'
        self.adapter = adapter
        self.stop = threading.Event()
        self.signal = threading.Event()
        self.status_cache = (0, {})
        self.status_lock = threading.Lock()
        from runtime_health import RuntimeHealth
        self.runtime_health = RuntimeHealth()
        self.provisioned = set()
        self.boot_id = secrets.token_hex(8)
        self.delete_lock = threading.Lock()
        self.bac_reset_lock = threading.RLock()
        self.deletion_signal = threading.Event()
        self.deletion_worker = None
        self.execution_lock = threading.RLock()
        self.executing_jobs = {}
        self.active_team_calls = {}
        self.agent_locks = {}
        self.executing_owners = set()
        self.executing_bac_owners = set()
        from protection_activity import ProtectionActivity
        self.protection_activity = ProtectionActivity()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS participants (
                  id TEXT PRIMARY KEY, token TEXT UNIQUE, csrf TEXT, profile TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, owner TEXT, kind TEXT, status TEXT, payload TEXT,
                  result TEXT, events TEXT, created REAL, updated REAL, due REAL);
                CREATE TABLE IF NOT EXISTS agent_deletions (owner TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS job_queue ON jobs(status,due,created);
                CREATE INDEX IF NOT EXISTS job_owner_created ON jobs(owner,created DESC);
                CREATE INDEX IF NOT EXISTS job_crew_chat ON jobs(owner,json_extract(payload,'$.crewRole'),created DESC) WHERE kind='crew-chat';
                DROP TABLE IF EXISTS pairs;
                DROP TABLE IF EXISTS phones;
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
                DELETE FROM metadata WHERE key='telegram-offset';
                CREATE TABLE IF NOT EXISTS agent_policies (owner TEXT NOT NULL, role INTEGER NOT NULL DEFAULT -1,
                    approved TEXT NOT NULL DEFAULT '[]', events TEXT NOT NULL DEFAULT '[]',
                    updating INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,role));
                CREATE TABLE IF NOT EXISTS event_surveys (token TEXT PRIMARY KEY, owner TEXT, job TEXT UNIQUE, definition TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS survey_responses (token TEXT, visitor TEXT, topic TEXT, experience TEXT, rating INTEGER, created REAL, PRIMARY KEY(token,visitor));
            ''')
            import model_reasoning
            model_reasoning.initialize(db)
            if 'role' not in {r['name'] for r in db.execute('PRAGMA table_info(agent_policies)')}:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE agent_policies RENAME TO agent_policies_legacy;
                    CREATE TABLE agent_policies (owner TEXT NOT NULL, role INTEGER NOT NULL DEFAULT -1,
                        approved TEXT NOT NULL DEFAULT '[]', events TEXT NOT NULL DEFAULT '[]',
                        updating INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,role));
                    INSERT INTO agent_policies(owner,approved,events,updating)
                        SELECT owner,approved,events,updating FROM agent_policies_legacy;
                    DROP TABLE agent_policies_legacy;
                    COMMIT;
                """)
            if 'denials' not in {r['name'] for r in db.execute('PRAGMA table_info(agent_policies)')}:
                db.execute("ALTER TABLE agent_policies ADD COLUMN denials TEXT NOT NULL DEFAULT '[]'")
            if 'reset_at' not in {r['name'] for r in db.execute('PRAGMA table_info(participants)')}:
                db.execute('ALTER TABLE participants ADD COLUMN reset_at REAL NOT NULL DEFAULT 0')
            db.execute('''CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY, participant TEXT NOT NULL, profile TEXT,
                created REAL, reset_at REAL NOT NULL DEFAULT 0)''')
            # The original agent keeps its ID, native identity, jobs and files.
            if not db.execute("SELECT 1 FROM metadata WHERE key='agent-collection-migrated'").fetchone():
                db.execute('''INSERT OR IGNORE INTO agents (id,participant,profile,created,reset_at)
                    SELECT id,id,profile,created,reset_at FROM participants''')
                db.execute("INSERT INTO metadata VALUES ('agent-collection-migrated','1')")
            if 'deleting' not in {r['name'] for r in db.execute('PRAGMA table_info(agents)')}:
                db.execute('ALTER TABLE agents ADD COLUMN deleting INTEGER NOT NULL DEFAULT 0')
            if 'progress' not in {r['name'] for r in db.execute('PRAGMA table_info(agent_deletions)')}:
                db.execute("ALTER TABLE agent_deletions ADD COLUMN progress TEXT NOT NULL DEFAULT 'Queued for cleanup'")
            db.execute('CREATE INDEX IF NOT EXISTS agents_participant ON agents(participant)')
            # Never silently replay a potentially completed side effect after a crash.
            if start_worker or recover:
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE kind IN ('crew','prepare') AND status IN ('queued','running','waiting','stopping')", (time.time(),))
                db.execute('UPDATE agent_policies SET updating=0')
                db.execute("UPDATE jobs SET status='error',result=?,updated=? WHERE status IN ('running','stopping','waiting')",
                           (json.dumps({'error': 'The app restarted during this task. Inspect saved files before retrying.'}), time.time()))
        self.initialize_crew_ownership()
        self.initialize_session_lifecycle()
        from browser_access import BrowserAccess
        self.browser_access = BrowserAccess(self)
        from studio_heartbeat import RadarHeartbeat
        self.heartbeat = RadarHeartbeat(self)
        self.retire_host_file_grants()
        os.chmod(self.db_path, 0o600)
        with self.db() as db:
            owners = [row['id'] for row in db.execute("SELECT id FROM agents WHERE deleting=0 AND kind='personal'")]
        import user_location
        from personal_voice import PRESET_UPDATES
        from role_boundaries import required_role_skills
        for owner in owners:
            profile = self.profile(owner)
            if profile:
                original = json.dumps(profile)
                if 'notes' in profile.get('skills', []):
                    profile['skills'] = list(dict.fromkeys('radar' if key=='notes' else key for key in profile['skills']))
                    if profile.get('purpose','').startswith('Watch my uploaded meeting notes every 30 seconds.'):
                        profile['purpose'] = 'Every 30 seconds, summarize one technical article or announcement not yet shared. Share useful discoveries in my chosen tone; skip politics, stocks and company earnings.'
                if profile.get('purpose') in PRESET_UPDATES:
                    profile['purpose'] = PRESET_UPDATES[profile['purpose']]
                missing = set(required_role_skills(profile.get('purpose', ''))) - set(profile.get('skills', []))
                if missing:
                    profile['skills'] = sorted(set(profile.get('skills', [])) | missing)
                migrated = json.dumps(profile)
                if migrated != original:
                    # Persist the final profile once; retain the legacy session copy.
                    with self.db() as db:
                        db.execute('UPDATE agents SET profile=? WHERE id=?', (migrated, owner))
                        db.execute('UPDATE participants SET profile=? WHERE id=?', (migrated, owner))
                runtime.write_workspace(self.workspace(owner), profile)
            user_location.sync(self.workspace(owner))
        with self.db() as db:
            teams = [r['owner'] for r in db.execute('SELECT c.owner FROM crew_contexts c JOIN participants p ON p.id=c.participant WHERE p.retiring=0 AND c.scenario="plan"')]
        for team in teams:
            self.initialize_workspace(team)
            self.initialize_crew_workspaces(team)
        if start_worker:
            with self.db() as db:
                for owner in owners:
                    profile=self.profile(owner)
                    if profile and 'radar' in profile.get('skills',[]):
                        try:self.heartbeat.disable(profile['id'])
                        except RuntimeError:
                            # One unavailable identity must not prevent startup.
                            # Its queued preparation and tick retry independently.
                            self.heartbeat.statuses[owner]={'state':'preparing'}
                        # A browser lease is required before restoring autonomous work.
                        # RadarHeartbeat.tick queues preparation only for connected owners.
            self.worker = threading.Thread(target=self.work, daemon=True, name='bac-agent-queue')
            self.deletion_worker = threading.Thread(target=self.clean_deletions, daemon=True, name='bac-cleanup-queue')
            self.chat_worker = threading.Thread(target=self.work, args=('chat',), daemon=True, name='bac-chat-queue')
            self.worker.start()
            self.chat_worker.start()
            self.deletion_worker.start()
            self.heartbeat_worker = threading.Thread(target=self.heartbeat.work, daemon=True, name='radar-heartbeat-relay')
            self.heartbeat_worker.start()

    def retire_host_file_grants(self):
        """Retire the removed file bridge without touching original host files.

        OpenClaw mirror mode replaces remote workspace contents before the next
        protected run, so removed transfer copies are not reintroduced remotely.
        """
        with self.db() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='host-file-grants-retired'").fetchone():
                return
            for row in db.execute('SELECT owner,role,approved FROM agent_policies').fetchall():
                approved = json.loads(row['approved'])
                websites = [key for key in approved if not key.startswith('file:')]
                if websites != approved:
                    db.execute('UPDATE agent_policies SET approved=? WHERE owner=? AND role=?',
                               (json.dumps(websites), row['owner'], row['role']))
            workspaces = self.directory / 'workspaces'
            if workspaces.is_dir() and not workspaces.is_symlink():
                for workspace in workspaces.iterdir():
                    inbox = workspace / 'inbox'
                    if workspace.is_symlink() or inbox.is_symlink() or not inbox.is_dir():
                        continue
                    for path in inbox.iterdir():
                        if re.fullmatch(r'approved-[0-9a-f]{64}\.txt(?:\.invalid-directory-[^/]+)?', path.name):
                            if path.is_dir() and not path.is_symlink():
                                shutil.rmtree(path)
                            else:
                                path.unlink()
            db.execute("INSERT INTO metadata VALUES ('host-file-grants-retired','1')")

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.execute('PRAGMA secure_delete=ON')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self, token=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM participants WHERE token=? AND retiring=0', (token,)).fetchone() if token else None
            if row:
                db.execute('UPDATE participants SET last_seen=? WHERE id=?', (time.time(),row['id']))
                return dict(row), False
            if db.execute('SELECT count(*) FROM participants').fetchone()[0] >= 500:
                raise Problem('This workshop is full. Ask the host to clear completed participants.', 503)
            row = {'id': secrets.token_hex(12), 'token': secrets.token_urlsafe(32),
                   'csrf': secrets.token_urlsafe(24), 'profile': None, 'created': time.time()}
            db.execute('INSERT INTO participants (id,token,csrf,profile,created) VALUES (:id,:token,:csrf,:profile,:created)', row)
            db.execute('UPDATE participants SET last_seen=? WHERE id=?', (row['created'],row['id']))
            db.execute('INSERT INTO agents (id,participant,created) VALUES (?,?,?)', (row['id'], row['id'], row['created']))
            return row, True

    def resolve_agent(self, participant, agent=None):
        """Resolve an explicitly selected agent within the authenticated account."""
        with self.db() as db:
            row = (db.execute("SELECT id FROM agents WHERE id=? AND participant=? AND kind='personal'", (agent, participant)).fetchone()
                   if agent else db.execute("SELECT id FROM agents WHERE participant=? AND kind='personal' ORDER BY created,id LIMIT 1", (participant,)).fetchone())
        if not row:
            raise Problem('Agent not found in your collection.', 404)
        return row['id']

    @staticmethod
    def require_available(db, owner):
        row = db.execute('SELECT profile,deleting FROM agents WHERE id=?', (owner,)).fetchone()
        if not row or not row['profile']:
            raise Problem('Agent not found.', 404)
        if row['deleting']:
            raise Problem('Agent deletion is pending. Retry Delete agent to finish cleanup.', 409)
        if db.execute('SELECT 1 FROM agent_policies WHERE owner=? AND updating=1', (owner,)).fetchone():
            raise Problem('This agent’s policy is being updated. Please wait.', 409)
        return row

    @staticmethod
    def require_manual_chat(profile):
        if 'radar' in (profile or {}).get('skills', []):
            raise Problem('Tech Radar uses Heartbeat. Manual chat is disabled.', 409)

    def require_idle(self, db, owner, *, except_job=''):
        executing = owner in self.executing_owners
        if executing and except_job:
            with self.execution_lock:
                executing = any(owner in owners for job, (owners, _) in self.executing_jobs.items() if job != except_job)
        if executing or db.execute("SELECT 1 FROM jobs WHERE owner=? AND id!=? AND status IN ('queued','running','waiting','stopping') AND NOT (kind='prepare-agent' AND status='queued')", (owner, except_job)).fetchone():
            raise Problem('Finish or cancel this agent’s pending missions before changing it.', 409)
        crews = db.execute("SELECT payload FROM jobs WHERE kind IN ('crew','crew-chat','prepare') AND status IN ('queued','running','waiting','stopping') AND owner IN (SELECT id FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?))", (owner,)).fetchall()
        if any(any(m.get('key') == owner for m in job_participants(json.loads(j['payload']))) for j in crews):
            raise Problem('This agent is assigned to a pending crew mission. Finish or cancel it first.', 409)

    @staticmethod
    def agent_profile(owner, data, *, previous_model=None):
        import personal_models
        name = text(data.get('name'), 32, 'Agent name')
        persona, skills = data.get('persona', 'guide'), data.get('skills', [])
        purpose = data.get('purpose', '')
        if not isinstance(purpose, str) or len(purpose) > 240 or any(ord(c) < 32 and c not in '\n\t' for c in purpose):
            raise Problem('Describe your agent in one sentence, up to 240 characters.')
        purpose = purpose.strip()
        tone_prompt = data.get('tonePrompt', '')
        if not isinstance(tone_prompt, str) or len(tone_prompt) > 800 or any(ord(c) < 32 and c not in '\n\t' for c in tone_prompt):
            raise Problem('Describe the tone in up to 800 characters.')
        tone, verbosity = data.get('tone', 'kind'), data.get('verbosity', 'balanced')
        if not isinstance(tone, str) or tone not in runtime.TONES:
            raise Problem('Choose an available speaking tone.')
        if not isinstance(verbosity, str) or verbosity not in runtime.VERBOSITIES:
            raise Problem('Choose an available answer length.')
        protection = data.get('protection', 'standard')
        if protection not in ('standard', 'openshell'):
            raise Problem('Choose OpenShell on or off.')
        if any(x in name for x in '\r\n<>') or not isinstance(persona, str) or persona not in runtime.PERSONAS:
            raise Problem('Choose a valid name and persona.')
        if not isinstance(skills, list) or len(skills) > len(runtime.SKILLS) or any(not isinstance(x, str) or x not in runtime.SKILLS for x in skills):
            raise Problem('Skills must be a list of available skills, or an empty list for none.')
        from role_boundaries import required_role_skills
        skills = set(skills) | set(required_role_skills(purpose))
        return {'name': name, 'persona': persona, 'purpose': purpose, 'tonePrompt': tone_prompt.strip(), 'tone': tone, 'verbosity': verbosity, 'skills': sorted(set(skills)),
                'avatar': avatar_for(owner, data.get('avatar')), 'id': 'bac-' + owner, 'protection': protection,
                'model': personal_models.validate(data['model'] if 'model' in data else personal_models.hiring_default(), previous=previous_model, lounge=True)}

    @staticmethod
    def unique_agent_name(db, participant, requested, exclude=None):
        used = {json.loads(row['profile'])['name'].strip().casefold()
                for row in db.execute('SELECT id,profile FROM agents WHERE participant=? AND profile IS NOT NULL', (participant,))
                if row['id'] != exclude}
        if requested.casefold() not in used:
            return requested
        match = re.fullmatch(r'(.*)_([2-9]|[1-9][0-9]+)', requested)
        base = match.group(1) if match else requested
        number = int(match.group(2)) + 1 if match else 2
        while True:
            suffix = '_' + str(number)
            candidate = base[:32-len(suffix)] + suffix
            if candidate.casefold() not in used:
                return candidate
            number += 1

    def initialize_crew_workspaces(self, owner, scenario=None):
        from scenarios import crew_member
        scenario = scenario or self.crew_scenario(owner)
        for role, member in enumerate(CREW_CATALOG):
            if member.get('retired'):continue
            profile = {**crew_member(member, scenario), '_scenario':scenario, 'skills':list(ROLE_SKILLS[role]), 'protection':member.get('protection','standard')}
            runtime.write_workspace(self.workspace(owner, role), profile, member['role'], overwrite=False)

    def initialize_workspace(self, owner):
        workspace = self.workspace(owner)
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        (workspace / 'inbox').mkdir(exist_ok=True)
        (workspace / 'artifacts').mkdir(exist_ok=True)
        import user_location
        user_location.sync(workspace)
        memory = workspace / 'MEMORY.md'
        if not memory.exists():
            memory.write_text('# Saved preferences\n', encoding='utf-8')

    def add_agent(self, participant, data):
        owner = secrets.token_hex(12)
        profile = self.agent_profile(owner, data)
        with self.new_agent_workspace(owner), self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM participants WHERE id=? AND retiring=0', (participant,)).fetchone():
                raise Problem('Open the Multi-Agent Studio page to start a session.', 401)
            if not db.execute('SELECT id FROM agents WHERE participant=? AND profile IS NOT NULL', (participant,)).fetchone():
                raise Problem('Create your first agent before adding another.')
            if db.execute("SELECT count(*) FROM agents WHERE participant=? AND kind='personal'", (participant,)).fetchone()[0] >= MAX_AGENTS:
                raise Problem('This studio supports up to %d personal agents per attendee.' % MAX_AGENTS, 409)
            profile['name'] = self.unique_agent_name(db, participant, profile['name'])
            self.initialize_workspace(owner)
            runtime.write_workspace(self.workspace(owner), profile)
            db.execute('INSERT INTO agents (id,participant,profile,created) VALUES (?,?,?,?)',
                       (owner, participant, json.dumps(profile), time.time()))
            self.queue_agent_preparation(db, owner, profile)
        self.signal.set()
        return {'agentId': owner, 'profile': profile}

    @contextlib.contextmanager
    def new_agent_workspace(self, owner, role=None):
        """Roll back only the fresh directory allocated by this creation attempt."""
        path = self.workspace(owner, role)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():raise RuntimeError('Agent workspace storage is redirected.')
        path.mkdir(mode=0o700)  # Never adopt or erase a pre-existing identity.
        identity = path.stat()
        try:
            yield
        except Exception:
            try:current = path.lstat()
            except FileNotFoundError:current = None
            if current and not path.is_symlink() and (current.st_dev,current.st_ino) == (identity.st_dev,identity.st_ino):
                shutil.rmtree(path)
            raise

    def workspace(self, owner, role=None):
        resource = self.crew_resources.get((owner,role)) if role is not None else None
        name = resource['workspace_name'] if resource else owner + ('-' + str(role) if role is not None else '')
        return self.directory / 'workspaces' / name

    def profile(self, owner):
        with self.db() as db:
            row = db.execute('SELECT profile FROM agents WHERE id=?', (owner,)).fetchone()
        if not row or not row['profile']:
            return None
        profile = json.loads(row['profile'])
        profile['avatar'] = avatar_for(owner, profile.get('avatar'))
        profile.setdefault('tone', 'kind')
        profile.setdefault('verbosity', 'balanced')
        from document_edits import edited_paths
        from agent_documents import CORE_DOCUMENTS, OPTIONAL_DOCUMENTS
        allowed = {name for name, _ in CORE_DOCUMENTS + OPTIONAL_DOCUMENTS}
        allowed.update('skills/bac-'+key+'/SKILL.md' for key in profile['skills'])
        workspace = self.workspace(owner)
        edited = {path for path in edited_paths(workspace) & allowed if (workspace/path).is_file()}
        if edited:
            profile['_editedDocuments'] = sorted(edited)
        return profile

    def onboard(self, owner, data):
        if self.profile(owner):
            raise Problem('Your agent already exists. Its identity and files are preserved.', 409)
        profile = self.agent_profile(owner, data)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            selected = db.execute("SELECT participant,profile,deleting FROM agents WHERE id=? AND kind='personal'", (owner,)).fetchone()
            if not selected:raise Problem('Agent not found. Refresh the studio before hiring.', 404)
            if selected['deleting']:raise Problem('Agent deletion is pending.', 409)
            if selected['profile']:raise Problem('Your agent was already created in another tab.', 409)
            participant = selected['participant']
            profile['name'] = self.unique_agent_name(db, participant, profile['name'], owner)
            self.initialize_workspace(owner)
            runtime.write_workspace(self.workspace(owner), profile)
            changed = db.execute("UPDATE agents SET profile=? WHERE id=? AND profile IS NULL AND kind='personal'", (json.dumps(profile), owner)).rowcount
            if changed:
                db.execute('UPDATE participants SET profile=? WHERE id=?', (json.dumps(profile), owner))
                self.queue_agent_preparation(db, owner, profile)
        if not changed:
            raise Problem('Your agent was already created in another tab.', 409)
        self.signal.set()
        return profile

    @staticmethod
    def queue_agent_preparation(db, owner, profile):
        # Durable, model-free warmup shares the worker and deletion fence with chat.
        registration_only = profile.get('protection') != 'openshell' and 'radar' not in profile.get('skills', [])
        if registration_only and 'weather' not in profile.get('skills', []):
            return
        payload = {'registrationOnly': True} if registration_only else {}
        now = time.time()
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (secrets.token_hex(12), owner, 'prepare-agent', 'queued', json.dumps(payload), '{}', '[]', now, now, now))

    def select_agent_model(self, owner, data):
        """Change an idle hire's model without copying a stale browser profile."""
        import personal_models
        with self.heartbeat.lock:
            with self.db() as db:
                row = self.require_available(db, owner)
                self.require_idle(db, owner)
                profile = json.loads(row['profile'])
            task_choice = data.get('stage') == 'team'
            if task_choice and 'model' in data and data['model'] is None:
                return self.configure(owner, {**profile, 'taskModel': None})
            if task_choice and data.get('model') == 'auto':
                import model_connections
                connection = model_connections.public()['connections']['api']
                if connection.get('provider') != 'nvidia':
                    return self.configure(owner, {**profile, 'taskModel': None})
            field = 'taskModel' if task_choice else 'model'
            model = personal_models.validate(data.get('model'), previous=profile.get(field, 'shared'))
            if not any(choice['id'] == model and choice['connected'] for choice in personal_models.public()['models']):
                raise Problem('This model is not connected. Refresh the choices or check Settings.', 409)
            # configure rechecks reservations after native I/O, before committing.
            if not task_choice and model == personal_models.DEFAULT:
                model = personal_models.EXPLICIT_LOCAL
            return self.configure(owner, {**profile, field: model})

    def configure(self, owner, data):
        profile = self.profile(owner)
        if not profile:
            raise Problem('Create your agent first.')
        if data.get('protection', profile.get('protection', 'standard')) != profile.get('protection', 'standard'):
            raise Problem('OpenShell protection is fixed when an agent is created.', 409)
        previous_task_model = profile.get('taskModel')
        task_model = data.get('taskModel', previous_task_model)
        profile = self.agent_profile(owner, {**data, 'avatar': data.get('avatar', profile['avatar']),
                    'purpose': data.get('purpose', profile.get('purpose', '')),
                    'tonePrompt': data.get('tonePrompt', profile.get('tonePrompt', '')),
                    'tone': data.get('tone', profile['tone']), 'verbosity': data.get('verbosity', profile['verbosity']),
                    'protection': profile.get('protection', 'standard'),
                    'model': data.get('model', profile.get('model', 'shared'))},
                    previous_model=profile.get('model', 'shared'))
        if task_model is not None:
            import personal_models
            profile['taskModel'] = personal_models.validate(task_model, previous=previous_task_model)
        # Perform native I/O before publishing the edit; then recheck whether
        # deletion or a new task won meanwhile. Never enqueue a retired identity.
        with self.heartbeat.lock:
            with self.db() as db:
                self.require_available(db, owner)
                self.require_idle(db, owner)
            self.heartbeat.disable(profile['id'])
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                previous = json.loads(self.require_available(db, owner)['profile'])
                self.require_idle(db, owner)
                participant = db.execute('SELECT participant FROM agents WHERE id=?', (owner,)).fetchone()['participant']
                profile['name'] = self.unique_agent_name(db, participant, profile['name'], owner)
                runtime.write_workspace(self.workspace(owner), profile)
                db.execute('UPDATE agents SET profile=? WHERE id=?', (json.dumps(profile), owner))
                db.execute('UPDATE participants SET profile=? WHERE id=?', (json.dumps(profile), owner))
                self.provisioned.discard(profile['id'])
                db.execute("DELETE FROM jobs WHERE owner=? AND kind='prepare-agent' AND status='queued'", (owner,))
                self.queue_agent_preparation(db, owner, profile)
                if profile['name'] != previous['name']:
                    from agent_documents import rename_edited_identity
                    rename_edited_identity(self.workspace(owner), profile['name'])
        self.signal.set()
        return profile

    def delete_agent(self, owner, data, *, enqueue_only=False):
        """Fence the identity first; retryable native cleanup precedes collection removal."""
        acquired = not enqueue_only and self.delete_lock.acquire(blocking=False)
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM agents WHERE id=?', (owner,)).fetchone()
                if not row or not row['profile']:
                    raise Problem('Agent not found.', 404)
                if db.execute('SELECT 1 FROM agent_policies WHERE owner=? AND updating=1', (owner,)).fetchone():
                    raise Problem('Wait for this agent’s policy update before deleting it.', 409)
                profile = json.loads(row['profile'])
                if data.get('name') != profile['name']:
                    raise Problem('This agent changed. Reopen Delete agent to confirm its name.', 409)
                pending = db.execute("SELECT * FROM jobs WHERE status IN ('queued','running','waiting','stopping') AND owner IN (SELECT id FROM agents WHERE participant=?)", (row['participant'],)).fetchall()
                affected = [j for j in pending if j['owner'] == owner or any(m.get('key') == owner for m in job_participants(json.loads(j['payload'])))]
                waiting = owner in self.executing_owners
                for job in affected:
                    running = job['status'] in ('running', 'stopping')
                    waiting = waiting or running
                    status = 'stopping' if running else 'cancelled'
                    events = json.loads(job['events'])
                    if job['status'] != 'stopping':
                        events.append({'time': time.time(), 'title': 'Agent deletion requested',
                                       'detail': profile['name'] + ' is being deleted. This task is stopping; no further steps will start.', 'role': 0})
                    db.execute('UPDATE jobs SET status=?,events=?,updated=? WHERE id=?',
                               (status, json.dumps(events[-40:]), time.time(), job['id']))
                # 2 waits for the worker to release all calls; 1 is native cleanup (retryable on failure).
                db.execute('UPDATE agents SET deleting=2 WHERE id=?', (owner,))
                db.execute('INSERT OR IGNORE INTO agent_deletions(owner) VALUES (?)',(owner,))
                if row['deleting']!=2:db.execute("UPDATE agent_deletions SET attempts=0,next_attempt=0,progress='Queued for cleanup' WHERE owner=?",(owner,))
            if not acquired:
                # Persist intent even when another agent owns the cleanup slot.
                # The worker drains this queue; callers only poll, never replay.
                if row['deleting'] != 2:self.signal.set()
                self.deletion_signal.set()
                return {'deleting': owner, 'agentId': owner}
            native_id = profile['id']
            try:
                if 'radar' in profile.get('skills',[]):self.heartbeat.disable(profile['id'])
                if waiting:
                    self.deletion_progress(owner, 'Waiting for current work to stop')
                    self.signal.set()
                    return {'deleting': owner, 'agentId': owner}
                # A hired identity owns one personal runtime. Shared team
                # resources have their own owner and never enter this plan.
                plan = [(profile['id'], self.workspace(owner))]
                inspect_unused = getattr(self.adapter, 'unregistered_deletion_targets', None)
                unused = inspect_unused(plan) if callable(inspect_unused) else set()
                self.deletion_progress(owner, 'Cleaning personal workspace')
                self.provisioned.discard(native_id)
                if native_id not in unused:
                    started = time.monotonic()
                    try:
                        self.adapter.remove(native_id, self.workspace(owner))
                    finally:
                        import logging
                        logging.info('Agent cleanup target %s took %.3fs', native_id, time.monotonic()-started)
                path = self.workspace(owner)
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)
                finalize = getattr(self.adapter, 'finalize_removal', None)
                if callable(finalize):
                    self.deletion_progress(owner, 'Removing remaining agent data')
                    finalize(native_id, path)
            except runtime.NativeCleanupPending as error:
                self.deletion_progress(owner, 'Waiting for runtime cleanup confirmation')
                # Only an acknowledged partial cleanup/confirmed draining run is
                # resumable. Never blindly replay unknown transport failures.
                with self.db() as db:
                    attempt=db.execute('SELECT attempts FROM agent_deletions WHERE owner=?',(owner,)).fetchone()['attempts']+1
                    db.execute('UPDATE agent_deletions SET attempts=?,next_attempt=? WHERE owner=?',
                               (attempt,time.time()+min(30,2**attempt),owner))
                    if attempt>=5:db.execute('UPDATE agents SET deleting=1 WHERE id=?',(owner,))
                if attempt>=5:raise Problem('Cleanup could not finish after recovery attempts. The agent remains paused; retry deletion after checking the runtime.',503) from None
                self.signal.set()
                return {'deleting':owner,'agentId':owner}
            except runtime.CleanupPrerequisiteError as error:
                self.diagnostics.agent_event(self, owner, 'agent.cleanup-blocked', error=error)
                self.deletion_progress(owner, 'Restart the agent runtime, then retry deletion.')
                with self.db() as db:
                    db.execute('UPDATE agents SET deleting=1 WHERE id=?', (owner,))
                raise Problem(str(error), 503) from None
            except Exception as error:
                import logging
                logging.exception('Native cleanup failed for %s', native_id)
                self.diagnostics.agent_event(self, owner, 'agent.cleanup-failed', error=error)
                self.deletion_progress(owner, 'Cleanup paused. Retry deletion.')
                with self.db() as db:
                    db.execute('UPDATE agents SET deleting=1 WHERE id=?', (owner,))
                # Keep the fence through errors/restarts; a partially removed identity must not run again.
                raise Problem('Deletion paused while cleaning ' + profile['name'] + ' (personal workspace). Native cleanup did not finish (' + type(error).__name__ + '). Retry deletion; completed cleanup is preserved.', 503) from None
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM survey_responses WHERE token IN (SELECT token FROM event_surveys WHERE owner=?)', (owner,))
                db.execute('DELETE FROM event_surveys WHERE owner=?', (owner,))
                for table in ('jobs', 'agent_policies', 'heartbeat_controls', 'heartbeat_receipts', 'agent_deletions'):
                    db.execute('DELETE FROM ' + table + ' WHERE owner=?', (owner,))
                db.execute('DELETE FROM agents WHERE id=?', (owner,))
                db.execute('UPDATE participants SET profile=NULL WHERE id=?', (owner,))
                next_agent = db.execute("SELECT id FROM agents WHERE participant=? AND kind='personal' ORDER BY created,id LIMIT 1", (row['participant'],)).fetchone()
                next_id = next_agent['id'] if next_agent else secrets.token_hex(12)
                if not next_agent:
                    # A fresh placeholder keeps the account usable without reusing deleted native identity.
                    db.execute('INSERT INTO agents (id,participant,created) VALUES (?,?,?)', (next_id, row['participant'], time.time()))
            with self.heartbeat.lock:
                self.heartbeat.statuses.pop(owner, None)
            self.protection_activity.forget(owner)
            return {'deleted': owner, 'agentId': next_id}
        finally:
            if acquired:self.delete_lock.release()

    def finish_pending_deletions(self):
        """Run between jobs, after every in-flight call and post-result write has returned."""
        if self.delete_lock.locked():
            return
        with self.db() as db:
            requests = db.execute('SELECT id,profile FROM agents LEFT JOIN agent_deletions ON owner=id WHERE deleting=2 AND coalesce(next_attempt,0)<=?',(time.time(),)).fetchall()
        for request in requests:
            try:
                self.delete_agent(request['id'], {'name': json.loads(request['profile'])['name']})
            except Problem:
                # Native failures keep deleting=1 for an explicit retry, not an endless cleanup loop.
                continue

    def deletion_progress(self, owner, message):
        with self.db() as db:
            db.execute('UPDATE agent_deletions SET progress=? WHERE owner=?', (message, owner))

    def clean_deletions(self):
        """Keep slow native cleanup off the HTTP handler and mission worker."""
        while not self.stop.is_set():
            self.deletion_signal.clear()
            self.finish_pending_deletions()
            self.clean_idle_sessions()
            self.deletion_signal.wait(1)

    def runtime_status(self, retry=False):
        # Manual retries share the probe lock and are rate limited across tabs.
        ttl = 2 if retry else 8
        if not self.status_cache[1] or time.monotonic() - self.status_cache[0] > ttl:
            with self.status_lock:
                if not self.status_cache[1] or time.monotonic() - self.status_cache[0] > ttl:
                    value = self.runtime_health.observe(self.adapter.status(), time.monotonic())
                    self.status_cache = (time.monotonic(), value)
        result = {**self.status_cache[1], 'instance': self.boot_id}
        import model_connections
        if model_connections.enabled():
            shared = model_connections.public()
            external = shared['connections']['api']
            if external['provider']=='nvidia' and external['ready']:
                import team_models
                result['teamModels']=team_models.available_models()
            import personal_models
            result['switchyard'] = personal_models.automatic_status(shared)
            result['personalModels'] = personal_models.public(shared)
            result.update(modelConnections=shared, model=bool(shared['loungeSource']), ready=bool(shared['loungeSource']) and bool(result.get('gateway')))
        self.diagnostics.observe_runtime(result)
        return result

    def files(self, owner, role=None, *, recursive=False, uploads_only=False, limit=100):
        from plan_inputs import internal_team_input
        result = []
        base = self.workspace(owner, role)
        if base.is_symlink():
            return []
        for category in (('inbox',) if uploads_only else ('inbox', 'artifacts')):
            folder = base / category
            if folder.is_symlink():
                continue
            try:
                paths = folder.rglob('*') if recursive else folder.glob('*')
                if limit != 1:
                    paths = sorted(paths)
            except (FileNotFoundError, NotADirectoryError):
                # A scenario reset can replace the directory during enumeration.
                continue
            for p in paths:
                try:
                    if uploads_only:
                        if p.suffix.lower() not in ('.txt', '.md', '.csv', '.pdf', '.pptx', '.xlsx', '.eml', '.png', '.jpg', '.webp'):
                            continue
                        # Chat images are original attachments. Plan inputs and handoffs are working copies.
                        chat_image = re.fullmatch(r'chat-[0-9a-f]{24}-\d+\.(png|jpg|webp)', p.name)
                        if not chat_image and internal_team_input(p.name, team=role is not None):
                            continue
                        if p.name.lower().endswith(('.pdf.txt', '.pptx.txt', '.xlsx.txt')) and p.with_suffix('').is_file():
                            continue
                    p = safe_file(base, str(p.relative_to(base)), True)
                    stat = p.stat()
                    result.append({'path': str(p.relative_to(base)), 'size': stat.st_size,
                                   'updated': stat.st_mtime, 'kind': category})
                    # The API already caps listings at 100. Do not resolve/stat
                    # every remaining file only to discard it at the end.
                    if len(result) == limit:
                        return result
                except (Problem, OSError):
                    # Reset and native tool writes can remove a file mid-listing.
                    continue
        return result

    def state(self, owner, scenario='plan'):
        from scenarios import validate
        from plan_inputs import internal_team_input
        validate(scenario)
        team = self.existing_crew_owner(owner, scenario)
        # Reuse exact listings within this response only. Native tool writes and
        # resets must be visible on the next poll without cache invalidation.
        listings = {}
        def listed_files(account, role=None, *, recursive=False):
            key = (account, role, recursive)
            if key not in listings:
                listings[key] = self.files(account, role, recursive=recursive)
            return listings[key]
        with self.db() as db:
            jobs = [self.public_job(r) for r in db.execute("SELECT * FROM jobs WHERE owner=? AND kind NOT IN ('crew','crew-chat','prepare','prepare-agent') AND created >= (SELECT reset_at FROM agents WHERE id=?) ORDER BY created DESC LIMIT 30", (owner, owner))]
            crew_chats = [self.public_job(r) for role in ACTIVE_ROLES for r in db.execute("SELECT * FROM jobs WHERE (owner=? OR owner=?) AND kind='crew-chat' AND json_extract(payload,'$.crewRole')=? ORDER BY created DESC LIMIT 30", (team, owner, role))]
            collection = db.execute('SELECT id,profile,deleting FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?) AND profile IS NOT NULL ORDER BY created,id', (owner,)).fetchall()
            active = [dict(j, payload=json.loads(j['payload'])) for j in db.execute("SELECT id,owner,status,payload,kind,due FROM jobs WHERE status IN ('queued','running','waiting','stopping') AND owner IN (SELECT id FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?)) ORDER BY created", (owner,))]
            agents = [{'key': r['id'], **json.loads(r['profile']), 'deleting': bool(r['deleting']), 'deletionWaiting': r['deleting'] == 2,
                       'pending': sum((j['owner'] == r['id'] and j['kind'] not in ('crew','prepare','prepare-agent')) or any(m.get('key') == r['id'] for m in job_participants(j['payload'])) for j in active if j['kind'] != 'crew-chat' or j['payload'].get('roundtable') or j['payload'].get('collaboration')),
                       'activity': personal_agent_activity(active, r['id'])} for r in collection]
            for agent in agents:
                agent['hasUploads'] = bool(self.files(agent['key'], recursive=True, uploads_only=True, limit=1))
                deletion = db.execute('SELECT progress FROM agent_deletions WHERE owner=?', (agent['key'],)).fetchone()
                agent['deletionProgress'] = deletion['progress'] if deletion else None
                latest = db.execute("SELECT id,status,CASE WHEN status='done' THEN substr(json_extract(result,'$.answer'),1,1200) ELSE NULL END AS answerPreview FROM jobs WHERE owner=? AND kind NOT IN ('crew','crew-chat','prepare','prepare-agent') AND created >= (SELECT reset_at FROM agents WHERE id=?) ORDER BY created DESC,rowid DESC LIMIT 1", (agent['key'], agent['key'])).fetchone()
                warmup = db.execute("SELECT status, json_extract(payload,'$.registrationOnly') AS registrationOnly FROM jobs WHERE owner=? AND kind='prepare-agent' ORDER BY created DESC LIMIT 1", (agent['key'],)).fetchone()
                agent['techRadar'] = self.heartbeat.status(agent['key'], agent)
                agent['workspacePreparation'] = warmup['status'] if warmup and not warmup['registrationOnly'] else None
                agent['latestMission'] = dict(latest, answerPreview=without_reply_prefix(latest['answerPreview'])) if latest else None
                agent['avatar'] = avatar_for(agent['key'], agent.get('avatar'))
                agent.setdefault('tone', 'kind')
                agent.setdefault('verbosity', 'balanced')
            bac_resetting = bool(db.execute("SELECT 1 FROM metadata m JOIN agents a ON (m.key='bac-reset-pending:'||a.participant OR m.key='bac-reset-pending:'||a.id) WHERE a.id=?",(team or owner,)).fetchone())
            reset_error = db.execute("SELECT m.value FROM metadata m JOIN agents a ON (m.key='bac-reset-error:'||a.participant OR m.key='bac-reset-error:'||a.id) WHERE a.id=?",(team or owner,)).fetchone()
            crew_chat_reset = self.crew_chat_reset_state(db, team or owner)
            roundtable_turns = self.roundtable_history(db, owner)
            names = {a['key']: a['name'] for a in agents}
            assignments = [{'job': j['id'], 'lead': j['owner'], 'name': names.get(j['owner'], 'team captain'), 'role': m['role'], 'status': j['status']}
                           for j in active if j['kind'] in ('crew','crew-chat') and j['owner'] != owner for m in job_participants(j['payload']) if m.get('key') == owner
                           and (m in j['payload'].get('roster', []) or j['payload'].get('roundtable', {}).get('replies', {}).get(owner, {}).get('status') not in ('done','error','cancelled'))]
        from live_plan_activity import snapshot as live_snapshot
        personal_profile = self.profile(owner)
        for job in jobs:
            if (job['status'] in ('running', 'stopping') and job['kind'] in ('chat', 'reminder')
                    and personal_profile):
                job['liveActivity'] = live_snapshot(self.adapter, {
                    'agent': personal_profile['id'], 'session': 'bac-' + owner,
                    'started': job['created'], 'role': None})
        import model_reasoning
        for job in crew_chats:
            plan = job['payload'].get('collaboration', {})
            observation = plan.pop('observation', None)
            if job['status'] == 'running' and observation and not plan.get('responseReady'):
                plan['liveActivity'] = live_snapshot(self.adapter, observation)
                current_model = model_reasoning.active_model(self, job['id'], observation=observation,
                                                             metrics=job['payload'].get('metrics'))
                if current_model:
                    plan['liveModel'] = current_model
        file_workspaces = []
        if team:
            candidates = [('team', None)] + [(str(role), role) for role, member in enumerate(CREW_CATALOG)
                if member.get('planEligible') is not False]
            file_workspaces = [name for name, role in candidates if self.files(team, role, recursive=True, uploads_only=True, limit=1)]
        memory = self.workspace(owner) / 'MEMORY.md'
        memory_text = ''
        try:
            memory_text = safe_file(self.workspace(owner), 'MEMORY.md', True).read_text(encoding='utf-8')
        except (Problem, UnicodeError):
            pass
        from team_models import selections
        from scenario_models import connection
        shell_preparing = any(j['owner'] == team and j['kind'] == 'prepare' and j['payload'].get('shellWarmup') for j in active)
        return {'shellPreparing':shell_preparing, 'scenario':scenario, 'scenarios':self.scenario_status(owner, files=listed_files), 'preparation':None,
                'teamConnection': connection(self, team), 'fileWorkspaces': file_workspaces,
                'hasFiles': any(a['key'] == owner and a['hasUploads'] for a in agents),
                'crewDocuments': [f for f in listed_files(team,0) if f['kind']=='inbox' and not internal_team_input(f['path'])] if team else [], 'teamSelections': selections(self,team,scenario), 'profile': personal_profile, 'jobs': jobs, 'crewChats': crew_chats, 'crewChatReset': crew_chat_reset, 'files': listed_files(owner),
                'techRadar': self.heartbeat.status(owner, personal_profile or {}),
                'memory': memory_text, 'agentId': owner, 'crewOwner': team, 'roundtableTurns': roundtable_turns,
                'agents': agents, 'agentLimit': MAX_AGENTS, 'assignments': assignments, 'bacResetting': bac_resetting,
                'bacResetError': reset_error['value'] if reset_error else None,
                'deleting': any(a['key'] == owner and a['deleting'] for a in agents),
                'protectionEvents': self.protection_activity.snapshot({a['key'] for a in agents}, team)}

    def crew_roster(self, owner):
        """Stable Open Task slots; retired slots are never eligible for dispatch."""
        return [{**member, 'name':member['name'], 'role':member['role'],
                 'skills':list(ROLE_SKILLS[role]), 'id':self.crew_native_id(owner,role),
                 'avatar':ROLE_AVATARS[role], 'key':None,
                 'protection':member.get('protection','standard'), 'tone':'kind', 'verbosity':'balanced'}
                for role,member in enumerate(CREW_CATALOG)]

    @staticmethod
    def public_job(row):
        job = {key: json.loads(row[key]) if key in ('payload', 'result', 'events') else row[key]
               for key in ('id', 'kind', 'status', 'payload', 'result', 'events', 'created', 'updated', 'due')}
        result = job['result']
        if isinstance(result, dict) and 'answer' in result:
            result['answer'] = without_reply_prefix(result['answer'])
        # Older saved runs may contain planner feedback intended for the model.
        if job['kind'] == 'crew-chat' and job['status'] == 'error' and isinstance(result, dict):
            error = result.get('error')
            plan = (job['payload'] or {}).get('collaboration') or {}
            if (not plan.get('calledRoles') and not plan.get('outputs') and isinstance(error, str)
                    and (plan_output_reason(error) or
                         error.startswith('Casey couldn’t finish assigning this task. No agents started work.'))):
                payload = job['payload'] or {}
                cause = plan.get('planningError') or (plan.get('planFormatRecovery') or {}).get('finalError') or error
                message = unassigned_team_message(payload.get('teamMode'), payload.get('roster') or [],
                                                  plan.get('task') or payload.get('prompt') or '', cause)
                result['error'] = message
                for event in job['events'] or []:
                    if event.get('detail') == error:
                        event['detail'] = message
        return job

    def upload(self, owner, data):
        role = data.get('crewRole')
        if 'crewRole' in data and (type(role) is not int or role != 0):
            raise Problem('Documents can be attached to Casey only.')
        if role is not None:
            owner = self.crew_owner(owner)
        if role is None and not self.profile(owner):
            raise Problem('Create your agent first.')
        name = text(data.get('name'), 100, 'File name')
        if role is not None:
            from plan_inputs import EVENT_INTERNAL_INPUTS
            if name in EVENT_INTERNAL_INPUTS:
                raise Problem('This filename is reserved for internal team work. Rename your document before uploading.')
        if '/' in name or '\\' in name:
            raise Problem('Use a file name without folders.')
        from document_upload import decode_document
        try:
            raw, extracted = decode_document(name, data)
        except ValueError as error:
            raise Problem(str(error)) from None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if role is None:self.require_available(db, owner)
            else:self.require_bac_not_resetting(db, owner)
            # Native OpenShell mirrors the workspace around tool calls. Do not
            # let its download overwrite a document uploaded mid-execution.
            self.require_idle(db, owner, except_job=self.shell_warmup_id(owner) if role == 0 else '')
            existing = {file['path'] for file in self.files(owner, role)}
            incoming = {'inbox/' + name}
            if extracted is not None:incoming.add('inbox/' + name + '.txt')
            if len(existing | incoming) > 80:
                raise Problem('Workspace file limit reached.')
            path = safe_file(self.workspace(owner, role), 'inbox/' + name)
            readable = safe_file(self.workspace(owner, role), 'inbox/' + name + '.txt') if extracted is not None else None
            # A binary document and its extracted text form one upload. Never
            # let a separate text upload silently replace that document's view.
            if name.lower().endswith(('.pdf.txt', '.pptx.txt', '.xlsx.txt')):
                original = safe_file(self.workspace(owner, role), 'inbox/' + name[:-4])
                if original.exists():
                    raise Problem('This name is reserved for text extracted from an existing document. Rename your text file before uploading.')
            if readable is not None and readable.exists() and not path.exists():
                raise Problem('A separate text document already uses the extracted-text file name. Rename this document before uploading.')
            path.write_bytes(raw)
            if readable is not None:
                readable.write_text(extracted, encoding='utf-8')
        return {'path': 'inbox/' + name, 'textPath': 'inbox/' + name + '.txt' if extracted is not None else 'inbox/' + name}

    def require_team_idle(self, db, owner, *, allow_shell_warmup=False):
        self.require_bac_not_resetting(db, owner)
        if not db.execute('SELECT 1 FROM agents WHERE id=? AND deleting=0', (owner,)).fetchone():
            raise Problem('This workspace is unavailable or being deleted.', 409)
        if db.execute('SELECT 1 FROM agent_policies WHERE owner=? AND role>=0 AND updating=1', (owner,)).fetchone():
            raise Problem('This agent’s policy is being updated. Please wait.', 409)
        if db.execute("SELECT 1 FROM jobs WHERE owner=? AND kind IN ('crew','crew-chat','prepare') AND status IN ('queued','running','waiting','stopping') AND NOT (? AND kind='prepare' AND coalesce(json_extract(payload,'$.shellWarmup'),0)=1)", (owner, allow_shell_warmup)).fetchone():
            raise Problem('The team is busy. Finish or stop its current work first.', 409)

    def enqueue(self, owner, data, source='web', due=0):
        if data.get('kind') in ('crew','prepare'):
            raise Problem('This workflow is retired. Send /goal to Casey in Open Task.',410)
        # Automatic Tech Radar heartbeats use their own delivery path.
        if data.get('kind', 'chat') in ('chat', 'reminder'):
            self.require_manual_chat(self.profile(owner))
        if data.get('kind', 'chat') in ('chat', 'reminder') and is_plan(data.get('prompt')):
            raise Problem('Send /goal to Casey in Open Task. Lounge agents accept direct messages only.')
        collaborative = data.get('kind') == 'crew-chat' and is_plan(data.get('prompt'))
        goal_example = data.get('goalExample')
        if goal_example is not None and (not collaborative or not isinstance(goal_example, str)
                                         or not re.fullmatch(r'[a-z0-9-]{1,40}', goal_example)):
            raise Problem('Choose a valid Open Task example.')
        if collaborative:
            from visitor_teams import team_mode
            mode = team_mode({k:v for k,v in data.items() if k != 'roster'})
            include_hired = mode != 'builtin'
            origin_role = data.get('crewRole')
            if type(origin_role) is not int or not 0 <= origin_role < len(ROLES):
                raise Problem('Choose a crew member.')
            if origin_role != 0:
                raise Problem('Send /goal to Casey in Open Task. Specialists accept direct messages only.')
            origin = {'owner': owner, 'role': origin_role}
            task = text(plan_task(data['prompt']), 5995, 'Task after /goal')
            owner = self.crew_owner(owner)
            data = {**data, 'kind':'crew-chat', 'crewRole':0, 'skill':None}
        profile = self.profile(owner)
        preset = data.get('kind') == 'crew-chat'
        if not profile and not preset:
            raise Problem('Create your agent first.')
        kind = data.get('kind', 'chat')
        if kind not in ('chat', 'reminder', 'crew-chat'):
            raise Problem('Unknown mission.')
        from chat_images import validate_images
        try:
            images = validate_images(data.get('images', []))
        except ValueError as error:
            raise Problem(str(error)) from None
        if images and kind not in ('chat', 'crew-chat'):
            raise Problem('Images are supported in chat messages.')
        prompt = text(data.get('prompt') or ('Describe the attached image.' if images else ''), 6000, 'Mission')
        skill = data.get('skill')
        if kind == 'crew-chat':
            role = data.get('crewRole')
            if type(role) is not int or not 0 <= role < len(ROLES):
                raise Problem('Choose a crew member.')
            if CREW_CATALOG[role].get('planEligible') is False:
                raise Problem('This specialist is no longer available. Ask Casey to assign the current team.')
            if skill:
                raise Problem('Crew skills are managed by the role.')
        if skill and skill not in profile['skills']:
            raise Problem('This agent has not equipped that skill.')
        payload = {'prompt': prompt, 'skill': skill, 'source': source}
        if kind == 'chat' and data.get('modelStage') == 'team':
            payload['modelStage'] = 'team'
        if kind == 'crew-chat':
            payload['crewRole'] = role
            if collaborative:
                payload['includeHiredAgents'] = include_hired
                payload['teamMode'] = mode
                if goal_example is not None:
                    payload['goalExample'] = goal_example
                payload['collaboration'] = {'task':task, 'origin':origin, 'activeRole':0, 'outputs':{}, 'handoffs':{}}
        if kind == 'reminder':
            delay = data.get('delay', 60)
            if type(delay) is not int or not 30 <= delay <= 86400:
                raise Problem('Schedule between 30 seconds and 24 hours from now.')
            due = time.time() + delay
        # A schedule may be created while offline, but immediate requests must fail visibly.
        team_request = kind == 'crew-chat'
        from scenario_models import readiness as team_readiness
        readiness = team_readiness(self, owner) if team_request else self.runtime_status()
        import personal_models
        ready = readiness.get('teamReady', readiness.get('ready')) if team_request else personal_models.ready(profile, readiness, payload.get('modelStage', 'lounge'))
        if kind != 'reminder' and not ready:
            if team_request:raise Problem('Check this scenario’s model connection and OpenClaw on the host.', 503)
            raise Problem(personal_models.unavailable(profile, payload.get('modelStage', 'lounge')) if readiness.get('gateway') else 'Agent runtime unavailable. Retry the connection to continue.', 503)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if profile or not preset:
                available = self.require_available(db, owner)
                if kind in ('chat', 'reminder'):
                    self.require_manual_chat(json.loads(available['profile']))
            elif not db.execute('SELECT 1 FROM agents WHERE id=? AND deleting=0', (owner,)).fetchone():
                raise Problem('Open a new studio session.', 404)
            if db.execute('SELECT 1 FROM agent_policies WHERE owner=? AND (CASE WHEN ? THEN role>=0 ELSE role=-1 END) AND updating=1', (owner, preset)).fetchone():
                raise Problem('This agent’s policy is being updated. Please wait.', 409)
            if kind in ('crew','crew-chat'):
                self.require_bac_not_resetting(db, owner)
            if kind == 'crew-chat' and role == 0 and db.execute(
                    "SELECT 1 FROM jobs WHERE owner=? AND kind='crew-chat' AND status IN ('queued','running','waiting','stopping') AND json_type(payload,'$.collaboration')='object' LIMIT 1", (owner,)).fetchone():
                raise Problem('Casey is coordinating the current plan. Wait for it to finish or stop it before sending a new message.', 409)
            if kind == 'crew-chat' and db.execute(
                    "SELECT 1 FROM jobs WHERE owner=? AND kind='crew-chat' AND status IN ('queued','running','waiting','stopping') AND (CASE WHEN json_type(payload,'$.collaboration')='object' THEN status IN ('running','stopping') AND json_extract(payload,'$.collaboration.activeRole')=? ELSE json_extract(payload,'$.crewRole')=? END) LIMIT 1", (owner, role, role)).fetchone():
                raise Problem('This agent is working. Wait for the current task to finish or stop it before sending a new message.', 409)
            if collaborative:
                self.require_team_idle(db, owner, allow_shell_warmup=True)
                from visitor_teams import capture
                if include_hired:
                    visitors, unavailable = capture(self, db, owner, wait_for_setup=mode == 'hired')
                    if mode == 'hired' and not visitors:
                        next_step = 'Check their status in the Lounge' if unavailable else 'Hire an agent'
                        if not unavailable:
                            skills = [name for name, _ in missing_skill_hints([], plan_task(prompt))]
                            if skills:
                                next_step = 'Hire agents with ' + ' and '.join(skills)
                        raise Problem('No hired agents are ready. ' + next_step + ' or choose Hired + Standby.', 409)
                    payload['roster'] = visitors
                    payload['unavailableVisitors'] = unavailable
                    payload['roundtable'] = self.capture_roundtable(db, owner, selected=[member['key'] for member in visitors])
                else:
                    # OFF keeps the established built-in task + personal reactions flow.
                    # The toggle controls specialist assignments, not closing reactions.
                    payload['roundtable'] = self.capture_roundtable(db, owner)
            if kind == 'chat':
                reserved = db.execute("SELECT payload FROM jobs WHERE kind='crew-chat' AND status IN ('queued','running','waiting','stopping') "
                    "AND owner IN (SELECT id FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?))", (owner,)).fetchall()
                if any(any(m.get('key') == owner for m in job_participants(json.loads(job['payload']))) for job in reserved):
                    raise Problem('This agent is collaborating with Casey. Finish or stop the team task first.', 409)
                # A greeting may use no tools. Keep the protected warmup queued
                # so the following tool request can still use a prepared workspace.
                if profile.get('protection') != 'openshell':
                    db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE owner=? AND kind='prepare-agent' AND status='queued'", (time.time(), owner))
            # Internal warmups retain deletion/policy fences, but do not spend the
            # attendee's three user-request slots while they open agent workspaces.
            pending = db.execute("SELECT count(*) FROM jobs WHERE kind NOT IN ('prepare-agent','prepare') AND owner IN (SELECT id FROM agents WHERE participant=(SELECT participant FROM agents WHERE id=?)) AND status IN ('queued','running','waiting','stopping')", (owner,)).fetchone()[0]
            if pending >= 3:
                raise Problem('Your collection has three pending missions. Finish or cancel one before adding another.', 429)
            self.initialize_workspace(owner)
            job = {'id': secrets.token_hex(12), 'owner': owner, 'kind': kind, 'status': 'queued',
                   'payload': json.dumps(payload), 'result': '{}', 'events': '[]',
                   'created': time.time(), 'updated': time.time(), 'due': due or time.time()}
            if images:
                import base64
                payload['images']=[]
                for index,(mime,raw) in enumerate(images):
                    extension={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[mime]
                    relative='inbox/chat-'+job['id']+'-'+str(index)+'.'+extension
                    safe_file(self.workspace(owner),relative).write_bytes(raw)
                    payload['images'].append({'path':relative,'mime':mime})
                job['payload']=json.dumps(payload)
            db.execute('INSERT INTO jobs VALUES (:id,:owner,:kind,:status,:payload,:result,:events,:created,:updated,:due)', job)
        self.signal.set()
        self.diagnostics.job(self, job['id'], 'job.queued')
        return {'id': job['id'], **({'collaboration':True, 'crewRole':0} if collaborative else {})}

    def event(self, job_id, title, detail, role=0, **changes):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT events,status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] == 'cancelled':return
            if row['status'] == 'stopping' and changes.get('status') in ('done', 'waiting', 'error'):
                changes['status'] = 'cancelled'
                title = 'Stopped at a safe boundary'
                detail = 'The active model call finished. Saved work remains; no next role will start.'
            events = json.loads(row['events'])
            events.append({'time': time.time(), 'title': title, 'detail': detail, 'role': role})
            values = {'events': json.dumps(events[-40:]), 'updated': time.time(), **changes}
            db.execute('UPDATE jobs SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?', [*values.values(), job_id])
        self.diagnostics.job(self, job_id, 'job.progress', role=role, phase=title, hint=detail)

    def decision(self, owner, job_id, action):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.profile(owner):
                self.require_available(db, owner)
            row = db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
            if not row:
                raise Problem('Mission not found.', 404)
            if action == 'cancel' and row['status'] in ACTIVE:
                status = 'stopping' if row['status'] in ('running', 'stopping') else 'cancelled'
                events = json.loads(row['events'])
                events.append({'time': time.time(), 'title': 'Stop requested' if status == 'stopping' else 'Mission cancelled',
                               'detail': 'An in-flight model call may finish and write files. Further roles will not start.' if status == 'stopping' else 'Removed from the queue; saved work is preserved.', 'role': 0})
                db.execute('UPDATE jobs SET status=?,events=?,updated=? WHERE id=?', (status, json.dumps(events[-40:]), time.time(), job_id))
                if status == 'stopping' and row['kind'] == 'crew-chat':
                    db.commit()
                    self.interrupt_team_calls([job_id])
                return {'status': status}
            raise Problem('This decision is not available.', 409)

    def stop_checkpoint(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:return True
        status = row['status']
        if status == 'stopping':
            self.event(job_id, 'Stopped at a safe boundary', 'Saved work is preserved. No further model call or channel reply will start.', status='cancelled')
            return True
        return status == 'cancelled'

    @staticmethod
    def crew_chat_reset_state(db, owner):
        account = db.execute('SELECT participant FROM agents WHERE id=?', (owner,)).fetchone()
        if not account:
            raise Problem('Agent not found.', 404)
        saved = db.execute("SELECT value FROM metadata WHERE key IN (?,?) ORDER BY CAST(json_extract(value,'$.at') AS REAL) DESC LIMIT 1",
                           ('crew-chat-reset:'+owner,'crew-chat-reset:'+account['participant'])).fetchone()
        return json.loads(saved['value']) if saved else {'at': 0, 'epoch': ''}

    def reset_crew_chats(self, owner, reset_event=False, *, pending_only=False):
        # HTTP and background completion can arrive together. Serialize reset
        # phases without holding a SQLite write lock across native policy I/O.
        with self.bac_reset_lock:
            with self.db() as db:
                pending = db.execute("SELECT m.value FROM metadata m JOIN agents a ON m.key='bac-reset-pending:'||a.participant WHERE a.id=?", (owner,)).fetchone()
            if reset_event and pending:
                owner = pending['value']  # A scenario retry also finishes its pending collection reset.
            return self._reset_crew_chats(owner, reset_event, pending_only=pending_only)

    def _reset_crew_chats(self, owner, reset_event=False, *, pending_only=False):
        """Clear the collection's crew chats and start fresh native conversations.

        Stage 3 reset removes team artifacts and attached documents after active work drains.
        Native transcripts remain stored but are not reused as conversation context.
        """
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            account = db.execute('SELECT participant FROM agents WHERE id=?', (owner,)).fetchone()
            if not account:
                raise Problem('Agent not found.', 404)
            scoped = bool(db.execute('SELECT 1 FROM crew_contexts WHERE owner=?',(owner,)).fetchone())
            owners = [owner] if scoped else [r['id'] for r in db.execute('SELECT id FROM agents WHERE participant=?', (account['participant'],))]
            slots = ','.join('?' for _ in owners)
            kinds = "('crew','crew-chat','prepare')" if reset_event else "('crew','crew-chat')"
            active = db.execute("SELECT id,status FROM jobs WHERE owner IN (" + slots + ") AND kind IN " + kinds + " AND status IN ('queued','running','waiting','stopping')", owners).fetchall()
            reset_scope = owner if scoped else account['participant']
            pending_key = 'bac-reset-pending:' + reset_scope
            error_key = 'bac-reset-error:' + reset_scope
            if pending_only and not db.execute('SELECT 1 FROM metadata WHERE key=?',(pending_key,)).fetchone():
                return {'reset':True}
            if pending_only and db.execute('SELECT 1 FROM metadata WHERE key=?',(error_key,)).fetchone():
                return {'reset':False,'resetting':True}
            if reset_event:
                db.execute('DELETE FROM metadata WHERE key=?',(error_key,))
                db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (pending_key,owner))
                for job in active:
                    status = 'stopping' if job['status'] in ('running','stopping') else 'cancelled'
                    db.execute('UPDATE jobs SET status=?,updated=? WHERE id=?', (status,time.time(),job['id']))
                # Keep a durable request until both native calls and post-processing
                # drain. Do not erase the rows that stop checkpoints depend on.
                updating = db.execute('SELECT 1 FROM agent_policies WHERE owner IN (' + slots + ') AND role>=0 AND updating=1', owners).fetchone()
                if any(job['status'] in ('running','stopping') for job in active) or self.executing_bac_owners.intersection(owners) or updating:
                    db.commit()
                    self.interrupt_team_calls(job['id'] for job in active)
                    self.signal.set()
                    return {'reset':False,'resetting':True}
            elif active:
                raise Problem('Finish or stop the active Multi-Agent Studio work before resetting. Nothing was reset.', 409)
            teams = [owner] if scoped else [r['owner'] for r in db.execute('SELECT owner FROM crew_contexts WHERE participant=?', (account['participant'],))]
            policies = []
            if reset_event:
                # An approval always creates a policy row before native I/O.
                # Unused standby identities need no provisioning or gateway call.
                for team in teams:
                    for row in db.execute('SELECT p.role,r.native_id FROM agent_policies p JOIN crew_resources r ON r.owner=p.owner AND r.role=p.role WHERE p.owner=?', (team,)):
                        if CREW_CATALOG[row['role']].get('protection') == 'openshell':
                            policies.append((team, row['role'], row['native_id']))
                            db.execute("UPDATE agent_policies SET approved='[]',updating=1 WHERE owner=? AND role=?", (team,row['role']))
        if policies:
            try:
                for team, role, native_id in policies:
                    report = self.adapter.policy_reset(native_id)
                    if report.get('status') not in ('applied', 'awaiting-first-mission'):
                        raise RuntimeError('OpenShell reset was not verified.')
            except Exception:
                message = 'OpenShell access could not be reset. Check the OpenShell connection, then retry Reset Open Task.'
                with self.db() as db:
                    db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (error_key,message))
                raise Problem(message, 503) from None
            finally:
                with self.db() as db:
                    for team, role, _ in policies:
                        db.execute('UPDATE agent_policies SET updating=0 WHERE owner=? AND role=?', (team,role))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not reset_event:
                self.require_bac_not_resetting(db, owner)
                if db.execute("SELECT 1 FROM jobs WHERE owner IN (" + slots + ") AND kind IN " + kinds + " AND status IN ('queued','running','waiting','stopping')", owners).fetchone():
                    raise Problem('Finish or stop the active Multi-Agent Studio work before resetting. Nothing was reset.', 409)
            if reset_event:
                # Only explicitly owned team workspaces; personal artifacts and uploads survive.
                workspaces = {self.workspace(team) for team in teams}
                for team in teams:
                    workspaces.update(self.workspace(team, role) for role in range(len(ROLES)))
                # Reject redirected parents before deleting anything. Artifact symlinks
                # themselves are unlinked without following their targets.
                for workspace in workspaces:
                    if workspace.parent.is_symlink() or workspace.is_symlink():
                        raise Problem('Team workspace is redirected; files were not cleared.', 409)
                for workspace in workspaces:
                    for category in ('artifacts', 'inbox'):
                        folder = workspace / category
                        if folder.is_symlink():
                            folder.unlink()
                        elif folder.is_dir():
                            shutil.rmtree(folder)
                        elif folder.exists():
                            folder.unlink()
                        if workspace.is_dir():
                            folder.mkdir(exist_ok=True)
                if teams:
                    team_slots = ','.join('?' for _ in teams)
                    resources = db.execute(
                        'SELECT native_id FROM crew_resources WHERE owner IN (' + team_slots + ')', teams).fetchall()
                    db.execute(
                        'UPDATE crew_resources SET model=NULL WHERE owner IN (' + team_slots + ')', teams)
                    for resource in resources:
                        self.provisioned.discard(resource['native_id'])
            # Rotate an account-scoped session epoch after artifact cleanup succeeds.
            # Native agent cleanup is independent; active crew calls are fenced above.
            reset = {'at': time.time(), 'epoch': secrets.token_hex(12)}
            removed = db.execute("DELETE FROM jobs WHERE owner IN (" + slots + ") AND kind='crew-chat'", owners).rowcount
            db.execute('INSERT OR REPLACE INTO metadata (key,value) VALUES (?,?)',
                       ('crew-chat-reset:' + reset_scope, json.dumps(reset)))
            if reset_event:
                for team, role, _ in policies:
                    db.execute("UPDATE agent_policies SET events='[]',denials='[]' WHERE owner=? AND role=?", (team,role))
                for team in teams:
                    db.execute('UPDATE agents SET reset_at=? WHERE id=?', (reset['at'],team))
                    self.protection_activity.forget(team)
                db.execute('INSERT OR REPLACE INTO metadata (key,value) VALUES (?,?)',
                           ('event-board-reset:' + reset_scope, str(reset['at'])))
                db.execute("DELETE FROM jobs WHERE owner IN (" + slots + ") AND kind='prepare'", owners)
                db.execute('DELETE FROM metadata WHERE key IN (?,?)',(pending_key,error_key))
                for team in teams:
                    db.execute('DELETE FROM metadata WHERE key IN (?,?)', ('bac-reset-pending:'+team,'bac-reset-error:'+team))
        return {'reset': True, 'removed': removed, 'crewChatReset': reset}

    def finish_pending_bac_resets(self):
        with self.db() as db:
            pending = db.execute("SELECT DISTINCT a.id FROM metadata m JOIN agents a ON m.value=a.id WHERE m.key LIKE 'bac-reset-pending:%'").fetchall()
        for row in pending:
            try:
                self.reset_crew_chats(row['id'], reset_event=True, pending_only=True)
            except Problem as error:
                if error.status not in (404, 503):raise

    def require_bac_not_resetting(self, db, owner):
        if db.execute("SELECT 1 FROM metadata m JOIN agents a ON (m.key='bac-reset-pending:'||a.participant OR m.key='bac-reset-pending:'||a.id) WHERE a.id=?",(owner,)).fetchone():
            raise Problem('Multi-Agent Studio is stopping its current work and resetting. Please wait.',409)

    def reset_board(self, owner):
        """Archive this agent's board, preserving identity, memory and files."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE owner=? AND status IN ('running','stopping')", (owner,)).fetchone():
                raise Problem('Stop the active mission and wait for it to finish before resetting. Nothing was reset.', 409)
            for row in db.execute("SELECT id,events FROM jobs WHERE owner=? AND status IN ('queued','waiting')", (owner,)).fetchall():
                events = json.loads(row['events']) + [{'time': time.time(), 'title': 'Board reset', 'detail': 'Pending mission cancelled before archiving.', 'role': 0}]
                db.execute("UPDATE jobs SET status='cancelled',events=?,updated=? WHERE id=?", (json.dumps(events[-40:]), time.time(), row['id']))
            db.execute('UPDATE agents SET reset_at=? WHERE id=?', (time.time(), owner))
            db.execute('UPDATE participants SET reset_at=? WHERE id=?', (time.time(), owner))
        return {'reset': True, 'preserved': ['agent', 'memory', 'files', 'archived evidence']}

    def evidence(self, owner, job_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
        if not row:
            raise Problem('Mission not found.', 404)
        # Explicit export by the participant. No cookie, credential or global log is included.
        return {'schema': 1, 'exported': time.time(), 'scope': 'This participant’s selected mission only',
                'runtime': {'version': runtime.VERSION, 'model': 'bac-local',
                            'events': 'App-observed lifecycle and handoffs; not native tool traces'},
                'mission': self.public_job(row)}

    def shell_warmup_id(self, team):
        return hashlib.sha256(f'shell:{team}:{self.boot_id}'.encode()).hexdigest()[:24]

    def start_shell_preparation(self, owner):
        if not getattr(self.adapter, 'openshell_configured', lambda: False)():
            return
        team = self.crew_owner(owner, 'plan')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                self.require_team_idle(db, team)
            except Problem:
                return
            if not db.execute('SELECT 1 FROM participants p JOIN agents a ON p.id=a.participant WHERE a.id=? AND p.retiring=0', (team,)).fetchone():
                return
            job_id = self.shell_warmup_id(team)
            now = time.time()
            payload = json.dumps({'background':True, 'shellWarmup':True, 'crewRole':9})
            if not db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                              (job_id, team, 'prepare', 'running', payload, '{}', '[]', now, now, now)).rowcount:
                return
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()

        def run():
            try:
                self.execute(row)
            except Exception:
                self.event(job_id, 'Shell preparation postponed', 'Shell will retry when assigned.', status='error')

        threading.Thread(target=run, daemon=True, name='bac-shell-preparation').start()

    def prepare_builtin_crew(self, owner, role, member):
        """Verify built-in protection before preparation, direct chat, and event work."""
        # Saved jobs from an older build must not restore an unprotected Dylan.
        from scenarios import crew_member
        definition = crew_member(CREW_CATALOG[role], self.crew_scenario(owner))
        member.update(name=definition['name'], role=definition['role'], _scenario=self.crew_scenario(owner))
        member['protection'] = CREW_CATALOG[role].get('protection', 'standard')
        agent_id = member['id']
        from team_models import selections
        selected = selections(self,owner)[role]
        member['_teamModel'] = None if selected.get('inherited') else selected['id']
        from scenario_models import prepare
        prepare(self, owner, member)
        control = member.get('_planControl') if role == 0 else None
        if control not in (None, 'none', 'read'):
            raise ValueError('Invalid Captain tool mode')
        mode = 'research-brief' if role == 8 and member.get('_researchBrief') else control
        modes = self.__dict__.setdefault('_crew_tool_modes', {})
        if agent_id not in self.provisioned or modes.get(agent_id) != mode:
            self.initialize_workspace(owner)
            self.adapter.register(agent_id, self.workspace(owner, role), member, CREW_CATALOG[role]['role'])
            self.provisioned.add(agent_id)
            modes[agent_id] = mode
        if member['protection'] != 'openshell':
            return None
        return self.ensure_crew_protection(owner, role, agent_id)

    def ensure_crew_protection(self, owner, role, agent_id, *, standby_member=None):
        from studio_policy import ProtectionNotVerified
        try:
            _, approvals = self.saved_policy(owner, role)
            report = self.adapter.policy_status(agent_id, 'openshell', approvals)
            if report['status'] == 'awaiting-first-mission':
                if standby_member is not None and agent_id not in self.provisioned:
                    # First dispatch still registers its selected model and tools.
                    self.adapter.register(agent_id, self.workspace(owner, role), standby_member, standby_member['role'])
                self.adapter.policy_prepare(agent_id)
                self.adapter.warm_workspace(agent_id)
                report = self.adapter.policy_status(agent_id, 'openshell', approvals)
            if report['status'] == 'needs-review':
                report = self.adapter.policy_apply(agent_id, approvals)
            if report['status'] != 'applied':
                raise ProtectionNotVerified(report['status'])
            return {key:report[key] for key in ('mode','status','checkedAt','rules','sandboxes') if key in report}
        except Exception:
            self.provisioned.discard(agent_id)
            raise

    def ensure_agent(self, owner, profile, role=None, *, model_stage='lounge'):
        role = None if role == 0 else role
        agent_id = profile['id'] if role is None else profile['id'] + '-r' + str(role)
        if role is not None:
            member = {'name':ROLES[role][0], 'persona':ROLES[role][2], 'skills':list(ROLE_SKILLS[role]), 'id':agent_id, 'role':ROLES[role][1]}
            self.prepare_builtin_crew(owner, role, member)
        else:
            import personal_models
            profile = dict(profile)
            personal_models.prepare(self, profile, model_stage)
            if agent_id in self.provisioned:return agent_id
            self.adapter.register(agent_id, self.workspace(owner), profile, None)
            self.provisioned.add(agent_id)
        return agent_id

    def record_usage(self, job_id, payload, answer, agent_id, name, stage=0, *, role=None, phase=None):
        metrics = getattr(answer, 'metrics', {})
        records = payload.setdefault('metrics', {})
        # Repairs are separate agent turns. Preserve every recorded response,
        # but do not count a response twice when it is saved after validation.
        turn = metrics.get('turnId')
        if turn and any(record.get('turnId') == turn and record.get('agent') == agent_id
                        for record in records.values()):
            return
        key, attempt = str(stage), 1
        while key in records:
            attempt += 1
            key = str(stage) + ':' + str(attempt)
        records[key] = {**metrics, 'agent': agent_id, 'name': name, 'stage': str(stage)}
        if role is not None:records[key]['role'] = role
        if phase is not None:records[key]['phase'] = phase
        # Save immediately, including when a later artifact validation fails.
        with self.db() as db:
            db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), job_id))
        self.diagnostics.job(self, job_id, 'model.turn-finished', model=metrics.get('model'),
                             inputTokens=metrics.get('input'), outputTokens=metrics.get('output'),
                             modelMs=metrics['runSeconds']*1000 if type(metrics.get('runSeconds')) in (float,int) else None)

    def agent_lock(self, agent_id):
        with self.execution_lock:
            return self.agent_locks.setdefault(agent_id, threading.RLock())

    def refresh_executing(self):
        self.executing_owners = set().union(*(owners for owners, _ in self.executing_jobs.values()))
        self.executing_bac_owners = set().union(*(owners for owners, bac in self.executing_jobs.values() if bac))

    def execute(self, row):
        self.diagnostics.job(self, row['id'], 'job.started')
        payload = json.loads(row['payload'])
        owners = {row['owner']} | {m['key'] for m in job_participants(payload) if m.get('key')}
        with self.execution_lock:
            self.executing_jobs[row['id']] = (owners, row['kind'] in ('crew','crew-chat','prepare'))
            self.refresh_executing()
        try:
            # Cover preparation, model calls and artifact collection with the same
            # identity lock used by individual collaboration stages.
            if row['kind'] == 'crew-chat' and not payload.get('collaboration'):
                lock = self.agent_lock(self.crew_native_id(row['owner'], payload['crewRole']))
            else:
                lock = contextlib.nullcontext()
            with lock:
                return self._execute(row)
        except Exception as error:
            self.diagnostics.job(self, row['id'], 'job.failed', error=error)
            if self.stop_checkpoint(row['id']):return
            raise
        finally:
            with self.execution_lock:
                self.executing_jobs.pop(row['id'], None)
                self.refresh_executing()
            self.signal.set()

    def _execute(self, row):
        owner, job_id = row['owner'], row['id']
        if self.stop_checkpoint(job_id):
            return
        payload = json.loads(row['payload'])
        # Every native continuation uses this job's Switchyard session.
        payload['_routingTurn'] = job_id
        profile = self.profile(owner)
        if row['kind'] == 'prepare' and payload.get('shellWarmup'):
            member = self.crew_roster(owner)[9]
            with self.agent_lock(member['id']):
                if self.stop_checkpoint(job_id):
                    return
                self.ensure_crew_protection(owner, 9, member['id'], standby_member=member)
            if not self.stop_checkpoint(job_id):
                self.event(job_id, 'Shell ready', 'Protected workspace verified.', status='done')
            return
        if row['kind'] == 'prepare-agent':
            self.ensure_agent(owner, profile)
            if self.stop_checkpoint(job_id):
                return
            report = self.check_protected_run(owner, profile)
            if report and report['status'] == 'awaiting-first-mission':
                if self.stop_checkpoint(job_id):
                    return
                self.event(job_id, 'Preparing workspace', 'Starting the protected workspace.', payload=json.dumps({'warmingWorkspace':True}))
                self.signal.set()
                self.adapter.warm_workspace(profile['id'])
            self.event(job_id, 'Agent ready', 'Background preparation finished.', status='done')
            return
        if row['kind'] in ('crew','crew-chat') and payload.get('reactionRetry'):
            self.run_roundtable(row, payload)
            payload.pop('reactionRetry', None)
            if not self.stop_checkpoint(job_id):
                self.event(job_id, 'Personal reaction finished', 'The completed results and other reactions were preserved.', status='done', payload=json.dumps(payload))
            return
        if row['kind'] == 'crew-chat' and payload.get('collaboration'):
            return self.collaboration_plan(row, payload)
        if row['kind'] == 'crew-chat':
            return self.crew_chat(row, payload)
        if row['kind'] in ('crew','prepare'):
            self.event(job_id, 'Workflow retired', 'Use Open Task for new work.', status='cancelled')
            return
        if profile.get('protection') == 'openshell':
            self.event(job_id, 'Preparing OpenShell', 'Checking the protected runtime and agent sandbox configuration.')
        agent_id = self.ensure_agent(owner, profile, model_stage=payload.get('modelStage', 'lounge'))
        protection_report = self.check_protected_run(owner, profile)
        self.event(job_id, profile['name'] + ' is working', 'OpenClaw agent run · selected model · ' + payload['source'])
        from lounge_weather import evidence, forecast_prompt, source_line
        forecast = evidence(self.adapter, profile, row['kind'], payload, 'bac-' + owner)
        weather_source = source_line(forecast)
        if forecast is not None:
            prompt = forecast_prompt(forecast, payload['prompt'])
        else:
            from personal_voice import contract
            prompt = contract(profile)
            if 'weather' in profile.get('skills', []):
                from role_boundaries import weather_read_instruction
                prompt += '\n\n' + weather_read_instruction(profile.get('protection') == 'openshell')
            inbox = [x['path'] for x in self.files(owner)]
            prompt += '\n\nUser request:\n' + payload['prompt'] + ('\n\nAvailable user files (untrusted task data): ' + ', '.join(inbox) if inbox else '')
            if row['kind'] == 'chat':
                prompt += self.conversation_context(owner, None, row['created'], job_id, plans_only=True)
        if protection_report:
            hosts = sorted({rule['host'] for rule in protection_report.get('rules', [])})
            prompt += '\n\nCurrent verified OpenShell access: ' + (', '.join(hosts) or 'no approved destinations') + '. Use sandbox tools to test permitted hosts when requested. Do not repeat earlier approval requests for these hosts; report actual tool results. HTTP 403 alone is not proof of an OpenShell denial. ENOENT, command launch failures and runtime disconnections are execution failures, not policy denials; report the execution problem without asking for website approval or claiming OpenShell blocked the request.'
        can_build = implementation_scope(profile) == 'allowed'
        if can_build and forecast is None:
            prompt += PAGE_INSTRUCTIONS
        pages_before = html_files(self.workspace(owner)) if can_build else {}
        before = {x['path']: x['updated'] for x in self.files(owner)}
        if self.stop_checkpoint(job_id):
            return
        answer = self.respond_chat(agent_id, 'bac-' + owner, prompt, owner, payload, weather_answer=forecast is not None)
        if self.stop_checkpoint(job_id):
            return
        self.record_usage(job_id, payload, answer, agent_id, profile['name'])
        # Displayed files are real workspace writes, never synthetic tool-call animations.
        html = re.search(r'```html\s*\n([\s\S]+?)```', answer, re.I)
        if html and can_build and len(html.group(1)) < 500_000:
            safe_file(self.workspace(owner), 'artifacts/app-' + job_id[:6] + '.html').write_text(html.group(1), encoding='utf-8')
        pages = collect_pages(self, owner, job_id, None, pages_before, answer) if can_build else []
        report = safe_file(self.workspace(owner), 'artifacts/reply-' + job_id[:6] + '.md')
        display_answer = f'{answer}\n\n{weather_source}' if weather_source else answer
        report.write_text(display_answer, encoding='utf-8')
        changed = [x['path'] for x in self.files(owner) if x['path'] not in before or x['updated'] > before[x['path']]]
        changed = [p for p in changed if not p.lower().endswith('.html')] + pages
        activity = getattr(answer, 'activity', None)
        if forecast is not None:
            activity = dict(activity or {})
            call = {'id': job_id + '-weather', 'tool': 'bac_weather', 'status': 'completed',
                    'target': forecast.get('location', {}).get('city', ''), 'action': 'Weather lookup'}
            activity.update(available=True, calls=[call, *activity.get('calls', [])])
        self.event(job_id, 'Result saved', ', '.join(changed) or 'Agent response received.',
                   result=json.dumps({'answer': display_answer, 'files': changed, 'activity':activity}), status='done')
        if self.stop_checkpoint(job_id):
            return

    def interrupt_team_calls(self, jobs):
        with self.execution_lock:
            for job_id in jobs:
                call = self.active_team_calls.get(job_id)
                if call:
                    call.request_stop()

    @contextlib.contextmanager
    def team_call(self, job_id, agent_id, session):
        abort = getattr(self.adapter, 'abort_session', None)
        if not job_id or not callable(abort):
            yield
            return
        call = ActiveTeamCall(abort, agent_id, session)
        with self.execution_lock:
            self.active_team_calls[job_id] = call
        try:
            # Reset can commit between the previous checkpoint and registration.
            if self.stop_checkpoint(job_id):
                raise RuntimeError('Open Task was stopped.')
            yield call.stop_requested
        finally:
            with self.execution_lock:
                self.active_team_calls.pop(job_id)
                call.finished.set()
            if call.worker:
                # Keep the agent lock until an issued abort can no longer hit
                # the next turn of a persistent conversation.
                call.worker.join()

    def respond_chat(self, agent_id, session, prompt, owner, payload, *, weather_answer=False):
        from artifact_references import relative_references
        options = {'json_response': True} if payload.get('_captainDecision') and payload.get('crewRole') == 0 else {}
        if weather_answer:
            options['weather_answer'] = True
        else:
            prompt += ('\nWhen describing saved deliverables, use workspace-relative paths such as '
                       'artifacts/research-brief.md, not absolute host or container paths. '
                       'Keep supplied verified artifact download references unchanged. '
                       'This is a presentation rule, not permission to read other workspaces.')
        options['execution_stage'] = payload.get('modelStage') or ('team' if payload.get('crewRole') is not None else 'lounge')
        if payload.get('_responseTimeout') is not None:
            options['timeout'] = payload['_responseTimeout']
        if payload.get('images'):
            import base64
            options['images'] = [{'mime': image['mime'], 'data': base64.b64encode(safe_file(self.workspace(payload.get('_imageSourceOwner', owner)), image['path'], True).read_bytes()).decode()} for image in payload['images']]
        import model_connections
        if model_connections.is_automatic(self, agent_id):
            identity = payload.get('_routingTurn', session) + '\0' + agent_id
            options['routing_session'] = hashlib.sha256(identity.encode()).hexdigest()
        team_job = payload.get('_routingTurn') if options['execution_stage'] == 'team' else None
        with self.agent_lock(agent_id), self.team_call(team_job, agent_id, session) as stop_requested:
            if stop_requested is not None:
                options['stop_requested'] = stop_requested
            answer = self.protected_response(agent_id, session, prompt, owner, payload.get('crewRole'), **options)
        return relative_references(answer, self.workspace(owner, payload.get('crewRole')),
                                   structured=options.get('json_response', False))

    def crew_chat(self, row, payload):
        owner, job_id, role = row['owner'], row['id'], payload['crewRole']
        with self.db() as db:
            member = {**CREW_CATALOG[role], 'id':self.crew_native_id(owner,role),
                      'skills':list(ROLE_SKILLS[role]), 'avatar':ROLE_AVATARS[role], 'key':None,
                      'protection':CREW_CATALOG[role].get('protection','standard')}
            reset = self.crew_chat_reset_state(db, owner)
        from scenarios import crew_member
        definition = crew_member(CREW_CATALOG[role], self.crew_scenario(owner))
        member['purpose'] = definition['collaboration']['description']
        agent_id = member['id']
        report = self.prepare_builtin_crew(owner, role, member)
        if report:
            payload['protection'] = report
            self.event(job_id, 'OpenShell verified', 'Saved OpenShell access verified. Unapproved destinations remain blocked.', role, payload=json.dumps(payload))
        self.event(job_id, member['name'] + ' is working', member['role'], role)
        if self.stop_checkpoint(job_id):
            return
        prompt = ('You are ' + member['name'] + ', the ' + definition['collaboration']['title'] + '. '
                  + member['purpose'] + '\nAnswer this direct message using your equipped skills. '
                  + 'Use the current message, selected files and supplied conversation context. Do not load unrelated prior tasks or transcripts. ' +
                  'This is a conversation, not a new crew mission. Do not claim other agents ran, '
                  'or send invitations or publish anything on the user’s behalf.\n'
                  + scope_contract(member) + '\n\n' + payload['prompt'])
        if role == 0:
            prompt += '\nCommunication style: ' + definition['collaboration'].get('voice', '')
        prompt += self.conversation_context(owner, role, row['created'], job_id, plans_only=True)
        session = self.crew_chat_session(owner, role) + ('-' + reset['epoch'] if reset['epoch'] else '')
        can_build = implementation_scope(member) == 'allowed'
        if can_build:
            prompt += PAGE_INSTRUCTIONS + DEMO_CODING_INSTRUCTIONS
        pages_before = html_files(self.workspace(owner, role)) if can_build else {}
        answer = self.respond_chat(agent_id, session, prompt, owner, payload)
        pages = collect_pages(self, owner, job_id, role, pages_before, answer) if can_build else []
        self.record_usage(job_id, payload, answer, agent_id, member['name'], role)
        # Direct Captain chat never starts a team project. Keep the reminder
        # deterministic rather than relying on the model to repeat it each turn.
        reply_text = str(answer)
        if role == 0:
            hint = ('참고로, 팀 프로젝트를 원한다면 메시지 앞에 `/goal`을 추가해줘.'
                    if re.search(r'[가-힣]', payload['prompt']) else
                    'For a team project, add `/goal` at the start of your message.')
            if hint not in reply_text:
                reply_text += '\n\n' + hint
        self.event(job_id, 'Reply ready', member['name'], role,
                   result=json.dumps({'answer': reply_text,'files':pages,'activity':getattr(answer,'activity',None)}), status='done')

    @staticmethod
    def chat_lane(row):
        payload = json.loads(row['payload'])
        return row['kind'] in ('chat', 'reminder') or (row['kind'] == 'crew-chat' and not payload.get('collaboration') and not payload.get('reactionRetry'))

    def next_job(self, lane=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Defense in depth for stale queued work after an interrupted edit.
            db.execute("DELETE FROM jobs WHERE status='queued' AND NOT EXISTS (SELECT 1 FROM agents WHERE agents.id=jobs.owner)")
            db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE status='queued' AND owner IN (SELECT id FROM agents WHERE deleting!=0)", (time.time(),))
            candidates = db.execute("SELECT * FROM jobs WHERE status='queued' AND due<=? AND NOT (kind IN ('prepare-agent','prepare') AND EXISTS (SELECT 1 FROM agent_policies WHERE owner=jobs.owner AND updating=1)) ORDER BY (kind='prepare-agent' OR (kind='prepare' AND coalesce(json_extract(payload,'$.background'),0)=1)),due,created", (time.time(),)).fetchall()
            active = db.execute("SELECT * FROM jobs WHERE status IN ('running','stopping')").fetchall()
            with self.execution_lock:
                finishing = set(self.executing_jobs)
            if finishing:
                active += [r for r in db.execute("SELECT * FROM jobs WHERE id IN (" + ','.join('?' for _ in finishing) + ")", tuple(finishing)) if r['status'] not in ('running','stopping')]
            row = None
            queued_chat_owners = {j['owner'] for j in candidates if j['kind'] == 'chat'}
            for candidate in candidates:
                if lane is not None and self.chat_lane(candidate) != (lane == 'chat'):
                    continue
                if candidate['kind'] == 'prepare-agent' and candidate['owner'] in queued_chat_owners:
                    continue
                cp = json.loads(candidate['payload'])
                blocked = False
                for busy in active:
                    bp = json.loads(busy['payload'])
                    related = {busy['owner']} | {m['key'] for m in job_participants(bp) if m.get('key')}
                    candidate_owners = {candidate['owner']} | {m['key'] for m in job_participants(cp) if m.get('key')}
                    if not candidate_owners.intersection(related):
                        continue
                    if candidate['kind'] == 'crew-chat' and busy['kind'] == 'prepare' and bp.get('shellWarmup'):
                        # Only Shell needs this preparation. Its native identity lock serializes both paths.
                        continue
                    # Registration is complete. Lounge chat can start inference while
                    # the Gateway serializes actual sandbox tools with the warmup.
                    if candidate['kind'] == 'chat' and busy['kind'] == 'prepare-agent' and busy['status'] == 'running' and bp.get('warmingWorkspace') is True:
                        continue
                    if candidate['kind'] == busy['kind'] == 'crew-chat' and candidate['owner'] == busy['owner']:
                        cr = cp.get('crewRole')
                        br = bp.get('collaboration', {}).get('activeRole', bp.get('crewRole'))
                        if not cp.get('collaboration') and not bp.get('reactionRetry') and cr != br:
                            continue
                    blocked = True
                    break
                if not blocked:
                    row = candidate
                    break
            if row:
                db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row['id']))
        return row

    def work(self, lane='background'):
        while not self.stop.is_set():
            try:
                if lane == 'background':
                    self.finish_pending_bac_resets()
                    if self.deletion_worker is None:self.finish_pending_deletions()
                row = self.next_job(lane)
            except sqlite3.OperationalError as error:
                # Startup/settings can briefly own the SQLite write lock. No job
                # has been claimed yet, so retry the queue, never a model call.
                if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():
                    raise
                self.stop.wait(.5)
                continue
            if row:
                try:
                    self.execute(row)
                except Exception as error:
                    import logging
                    logging.exception('Mission %s failed', row['id'])
                    message = str(error) if isinstance(error, (RuntimeError, Problem)) else 'Task failed. Check the host application logs and saved files before retrying.'
                    self.event(row['id'], 'Mission needs attention', message, status='error', result=json.dumps({'error': message}))
            else:
                self.signal.wait(1)
                self.signal.clear()
