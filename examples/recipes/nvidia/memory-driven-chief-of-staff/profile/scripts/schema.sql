-- Ledger store for the memory-driven chief-of-staff recipe.
--
-- Target runtime : SQLite bundled with Hermes 0.19.0 (the version the current
--                  NemoClaw agent image pins).
-- Location       : $HERMES_HOME/workspace/ledger/state.db
--                  `workspace` is user-owned, so this file survives
--                  `hermes profile install --force` and `hermes profile update`.
--                  Verified empirically on Hermes 0.19.0.
-- Writer         : scripts/apply_decisions.py is the ONLY writer. The model
--                  never emits SQL; it returns a decision envelope as JSON.
--
-- Privacy note   : `items` retains message subjects, senders and bodies once a
--                  source is connected. The containing directory is created
--                  0700. Body retention is not implemented in this phase; it
--                  arrives with the connectors that produce bodies.

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '7');


-- ---------------------------------------------------------------------------
-- 0) sources — the systems messages can arrive from.
--
--    A table rather than a CHECK list on `items.source`. The list was
--    `CHECK (source IN ('email','slack'))`, which meant a third connector
--    could not write a single row until someone shipped a schema migration —
--    and SQLite cannot alter a CHECK, so that migration is a full table
--    rebuild. Adding a source is now an INSERT, and the foreign key still
--    refuses a typo, which is what the CHECK was actually for.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    name      TEXT PRIMARY KEY,
    added_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT OR IGNORE INTO sources(name) VALUES ('email'), ('slack');


-- ---------------------------------------------------------------------------
-- 1) items — every inbound message we have looked at.
--    Intake is idempotent on source_id, so re-reading a source is safe.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
    -- Email: the Graph message id. Slack: "<channel_id>:<ts>", because a
    -- Slack timestamp is only unique within its channel.
    source_id   TEXT PRIMARY KEY,
    source      TEXT NOT NULL REFERENCES sources(name),
    scope       TEXT NOT NULL,              -- mail folder id / slack channel id
    thread_ref  TEXT,                       -- groups replies; NULL when standalone
    -- ISO-8601 UTC. Slack returns an epoch float and must be converted at
    -- ingest so both sources sort together.
    event_at    TEXT NOT NULL,
    sender      TEXT,
    -- Who the sender is, as opposed to what they are called.
    --
    -- `sender` holds a display name whenever the source supplies one, and a
    -- display name is not an identity: two people called the same thing share
    -- a page, and the second overwrites the first's history under the first's
    -- name. Neither is recoverable afterwards, because nothing else in the
    -- row distinguishes them.
    --
    -- Both normalizers already compute a stable value — a mail address, a
    -- Slack user id — and until now dropped it before the insert. It is kept
    -- here so a page can be named after the person rather than after the
    -- string they happen to be displayed as. Nullable: rows collected before
    -- this column existed have none, and a collector that cannot supply one
    -- is not a reason to refuse the message.
    sender_key  TEXT,                       -- address or user id, never a name
    -- What the person is called *by the source*, as opposed to who they are
    -- (`sender_key`) or what they are displayed as (`sender`).
    --
    -- A Slack `@handle`, a GitHub login, a mail local part. Three distinct
    -- things, and conflating any two of them loses something: the handle is
    -- unique within its source but the person can change it, so it cannot be
    -- an identity; the display name is neither unique nor stable; the stable
    -- id is neither readable nor something anyone would recognise.
    --
    -- Kept because it is the strongest evidence a source gives for the same
    -- person appearing in another one, and because it is what a user
    -- recognises when asked whether two identities are the same colleague.
    -- NULL when the source has no such concept — mail does not.
    sender_handle TEXT,
    subject     TEXT,                       -- NULL for slack
    body        TEXT,
    -- Set when the retention pass clears `body`, and never otherwise. It is
    -- what tells a cleared message from one that never carried text: both
    -- leave `body` NULL, and only one of them is a message somebody sent.
    body_cleared_at TEXT,
    -- Set when the source says the message is gone. Distinct from
    -- `body_cleared_at`, which records this recipe ageing the text out on its
    -- own schedule: one is the person deleting something, the other is us
    -- forgetting it, and a report that conflates them answers the wrong
    -- question. The row survives either way, because obligations and events
    -- hang off `source_id` and removing it would break the audit trail.
    deleted_at    TEXT,
    -- The message's own identity, as opposed to its position in a folder.
    --
    -- Needed to tell a deletion from a move: the delta query reports both
    -- identically and the per-folder id changes when a message moves, so
    -- this is the only thing that survives to ask about. Kept on the row
    -- rather than in a bounded map beside it — a map that evicts turns an
    -- older message being filed away into a deletion, and clears its body.
    internet_message_id TEXT,
    permalink   TEXT,                       -- link back to the source system

    -- Normalized across sources, because the judging rules ask the same
    -- question of both: was this aimed at the user, or did they merely
    -- receive it? Email: a To recipient is 'direct', Cc-only is 'broadcast'.
    -- Slack: an im/mpim is 'direct', a channel message that @-mentions the
    -- user is 'mentioned', anything else is 'broadcast'.
    addressing  TEXT CHECK (addressing IN ('direct','mentioned','broadcast')),
    -- Email only; Slack tracks read state per channel, not per message.
    unread      INTEGER CHECK (unread IN (0,1)),
    state       TEXT NOT NULL
                CHECK (state IN ('pending','judged','skipped'))
                DEFAULT 'pending',
    state_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    -- Authorship relative to the connected user. NULL means unrecorded;
    -- pre-C1 collectors keep this value until their separate upgrades.
    direction   TEXT CHECK (direction IN ('inbound','outbound')),
    -- Resolution deadline measured from the outbound event. Counterparty
    -- fields describe the recipient; sender fields always describe the author.
    counterparty_pending_until TEXT,
    source_account TEXT,
    counterparty_key TEXT,
    counterparty_name TEXT,
    counterparty_handle TEXT,
    counterparty_basis TEXT CHECK (counterparty_basis IN
        ('single_recipient','dm','mention','reply')),
    counterparty_candidates TEXT
);

-- ---------------------------------------------------------------------------
-- 1b) identity_links — the user's answer to "are these the same person?"
--
--    An identity is a (source, key) pair, and one person holds as many as
--    they have places to write from. Nothing in the data says which belong
--    together: a shared display name is not evidence, and guessing from one
--    is precisely the mistake `sender_key` exists to prevent. Only the user
--    can say, so only the user's answer is recorded here.
--
--    Pairs, not groups, because pairs compose. Confirming A~B and B~C makes
--    A~C true without asking a third time, and a fourth identity is one more
--    pair rather than a new shape. The grouping is a disjoint-set union over
--    the confirmed rows; see `identity.py`.
--
--    Rejections are kept for the same reason as confirmations. A candidate
--    the user has already dismissed must not be proposed again on the next
--    run — an unresolved question re-asked nightly is how a job that should
--    be idle wakes the agent forever.
--
--    Each pair is stored once, with the lexicographically smaller identity
--    on the left, so (A,B) and (B,A) cannot both exist and disagree.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS identity_links (
    left_source   TEXT NOT NULL REFERENCES sources(name),
    left_key      TEXT NOT NULL,
    right_source  TEXT NOT NULL REFERENCES sources(name),
    right_key     TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('confirmed','rejected')),
    decided_at    TEXT NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- How the answer was obtained. Only the user decides, but the route
    -- matters when reading back a decision months later.
    decided_via   TEXT NOT NULL DEFAULT 'user',
    PRIMARY KEY (left_source, left_key, right_source, right_key),
    -- The ordering invariant, enforced rather than remembered.
    CHECK ((left_source, left_key) < (right_source, right_key))
);

-- Resolving a person means walking every confirmed link touching an
-- identity, from either side.
CREATE INDEX IF NOT EXISTS idx_links_left
    ON identity_links(left_source, left_key) WHERE status = 'confirmed';
CREATE INDEX IF NOT EXISTS idx_links_right
    ON identity_links(right_source, right_key) WHERE status = 'confirmed';


-- _db.ensure_store creates idx_items_pending and
-- idx_items_counterparty_pending after migration. Creating indexes on the
-- new columns here would fail before an older items table can be upgraded.
-- Body pruning reads this.
CREATE INDEX IF NOT EXISTS idx_items_event_at ON items(event_at) WHERE body IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 2) obligations — the revisable judgment. At most one per item.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS obligations (
    id              TEXT PRIMARY KEY,       -- generated by the writer, never by the model
    source_id       TEXT NOT NULL UNIQUE
                    REFERENCES items(source_id) ON DELETE CASCADE,

    -- what the model judged
    title           TEXT NOT NULL,
    context         TEXT,
    urgency_reason  TEXT,
    kind            TEXT CHECK (kind IN ('response','action')),
    est_effort      TEXT CHECK (est_effort IN ('minutes','hours','day','multi_day')),

    -- ranking
    priority        TEXT NOT NULL CHECK (priority IN ('high','medium','low')),
    manual_priority TEXT CHECK (manual_priority IN ('high','medium','low')),
    global_rank     INTEGER,
    -- The position the model gave this row when it was last judged, within
    -- that batch only. Tier and global_rank are derived from the whole open
    -- population afterwards; a batch cannot see its siblings.
    batch_rank      INTEGER,
    -- Did this row pass the intent gate on its last ranking pass?
    -- Recorded so the shortlist can explain WHY a row is capped at medium:
    -- "urgent, but not something you chose to work on" is a different answer
    -- from "not urgent". The gate itself is defined in the review skill.
    intent_gated    INTEGER NOT NULL DEFAULT 0 CHECK (intent_gated IN (0,1)),

    -- lifecycle
    status          TEXT NOT NULL
                    CHECK (status IN ('open','done','ignored'))
                    DEFAULT 'open',
    snoozed_until   TEXT,
    snooze_count    INTEGER NOT NULL DEFAULT 0,

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reviewed_at     TEXT                    -- NULL = never reviewed; drives selection
);

-- Review selector: stalest open rows first, NULL (never reviewed) ahead of all.
CREATE INDEX IF NOT EXISTS idx_obl_review ON obligations(status, reviewed_at);
-- Shortlist read path.
CREATE INDEX IF NOT EXISTS idx_obl_rank ON obligations(status, global_rank);
-- Two open rows must never claim the same position. Enforced here as well as
-- in code, because a duplicate rank is the visible symptom of ranking a batch
-- instead of the population.
CREATE UNIQUE INDEX IF NOT EXISTS idx_obl_rank_unique
    ON obligations(global_rank) WHERE status='open' AND global_rank IS NOT NULL;
-- Wake-up scan for expiring snoozes.
CREATE INDEX IF NOT EXISTS idx_obl_snooze ON obligations(status, snoozed_until)
    WHERE snoozed_until IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS obligations_touch
AFTER UPDATE ON obligations
BEGIN
    UPDATE obligations
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
     WHERE id = NEW.id;
END;


-- ---------------------------------------------------------------------------
-- 3) events — append-only audit. Never pruned, never updated.
--    This is what makes "corrections train policy" checkable rather than
--    asserted: the policy generator counts user-actor rows.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    obligation_id TEXT NOT NULL REFERENCES obligations(id) ON DELETE CASCADE,
    ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    event_type    TEXT NOT NULL CHECK (event_type IN (
                      'created','reranked','snoozed','unsnoozed',
                      'ignored','restored','completed','priority_override')),
    actor         TEXT NOT NULL CHECK (actor IN ('agent','user')),
    before_json   TEXT,
    after_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_obl ON events(obligation_id, ts);
-- Policy generator reads this: user corrections only.
CREATE INDEX IF NOT EXISTS idx_events_corrections ON events(actor, event_type, ts);


-- ---------------------------------------------------------------------------
-- 4) cursors — per (source, scope) watermark, advanced in the SAME transaction
--    as the rows it covers. Crash leaves either both or neither.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cursors (
    source     TEXT NOT NULL,
    scope      TEXT NOT NULL,
    cursor     TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (source, scope)
);

-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

CREATE TABLE IF NOT EXISTS memory_control (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    protocol_version INTEGER NOT NULL CHECK (protocol_version = 1),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1))
);
INSERT OR IGNORE INTO memory_control VALUES (1, 1, 0);

CREATE TABLE IF NOT EXISTS pages (
    page_id TEXT PRIMARY KEY,
    page_type TEXT NOT NULL CHECK (page_type IN ('projects', 'patterns', 'concepts')),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'active', 'retired', 'deleted')),
    path TEXT UNIQUE,
    path_key TEXT UNIQUE,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((path IS NULL) = (path_key IS NULL)),
    CHECK (state = 'deleted' OR path IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS page_paths (
    path_key TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    disposition TEXT NOT NULL CHECK (disposition IN ('reserved', 'canonical', 'alias', 'tombstone'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_canonical_path_per_page ON page_paths(page_id)
    WHERE disposition = 'canonical';

CREATE TABLE IF NOT EXISTS page_operations (
    operation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    store_instance_id TEXT NOT NULL,
    op_type TEXT NOT NULL CHECK (op_type IN (
        'create', 'update', 'adopt', 'review_adoption', 'rename', 'merge',
        'retire', 'delete', 'resolve', 'legacy_write', 'log_only', 'repair_index')),
    actor TEXT NOT NULL CHECK (actor IN ('agent', 'user', 'maintenance')),
    status TEXT NOT NULL CHECK (status IN (
        'prepared', 'applying', 'blocked_diverged', 'complete', 'cancelled', 'superseded')),
    effects_json TEXT NOT NULL,
    plan_digest TEXT NOT NULL CHECK (length(plan_digest) = 64),
    supersedes_id TEXT REFERENCES page_operations(operation_id),
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unfinished_memory_operation ON page_operations((1))
    WHERE status IN ('prepared', 'applying', 'blocked_diverged');

CREATE TABLE IF NOT EXISTS managed_fields (
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    field_path TEXT NOT NULL,
    content_origin TEXT NOT NULL DEFAULT 'adopted'
        CHECK (content_origin IN ('generated', 'adopted')),
    ownership_operation_id TEXT NOT NULL REFERENCES page_operations(operation_id),
    review_operation_id TEXT REFERENCES page_operations(operation_id),
    ownership_policy TEXT NOT NULL CHECK (ownership_policy IN ('cas_protected', 'write_once', 'additive')),
    last_content_hash TEXT,
    last_evidence_digest TEXT,
    initialized INTEGER NOT NULL DEFAULT 0 CHECK (initialized IN (0, 1)),
    awaiting_first_review INTEGER NOT NULL DEFAULT 1 CHECK (awaiting_first_review IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (page_id, field_path),
    CHECK (last_content_hash IS NULL OR length(last_content_hash) = 64),
    CHECK (
        (content_origin = 'generated' AND awaiting_first_review = 0
            AND review_operation_id IS NULL)
        OR
        (content_origin = 'adopted' AND (
            (awaiting_first_review = 1 AND review_operation_id IS NULL)
            OR (awaiting_first_review = 0 AND review_operation_id IS NOT NULL)
        ))
    )
);

CREATE TABLE IF NOT EXISTS operation_pages (
    operation_id TEXT NOT NULL REFERENCES page_operations(operation_id),
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    PRIMARY KEY (operation_id, page_id)
);

CREATE TABLE IF NOT EXISTS memory_steps (
    operation_id TEXT NOT NULL REFERENCES page_operations(operation_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    kind TEXT NOT NULL CHECK (kind IN ('page', 'sidecar', 'index', 'log', 'registry', 'audit')),
    resource_key TEXT NOT NULL,
    target_path TEXT,
    before_presence TEXT NOT NULL CHECK (before_presence IN ('absent', 'present')),
    before_hash TEXT,
    after_presence TEXT NOT NULL CHECK (after_presence IN ('absent', 'present')),
    after_hash TEXT,
    before_bytes BLOB,
    after_bytes BLOB,
    payload_json TEXT,
    payload_cleared_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'conflict')),
    applied_at TEXT,
    PRIMARY KEY (operation_id, ordinal),
    UNIQUE (operation_id, resource_key),
    CHECK ((before_presence = 'absent' AND before_hash IS NULL) OR
           (before_presence = 'present' AND length(before_hash) = 64 AND before_hash IS NOT NULL)),
    CHECK ((after_presence = 'absent' AND after_hash IS NULL) OR
           (after_presence = 'present' AND length(after_hash) = 64 AND after_hash IS NOT NULL)),
    CHECK ((kind IN ('registry', 'audit') AND target_path IS NULL) OR
           (kind IN ('page', 'sidecar', 'index', 'log') AND target_path IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS page_events (
    event_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE REFERENCES page_operations(operation_id),
    actor TEXT NOT NULL CHECK (actor IN ('agent', 'user', 'maintenance')),
    event_type TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_resolutions (
    resolution_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES page_operations(operation_id),
    page_id TEXT REFERENCES pages(page_id),
    resolution_type TEXT NOT NULL CHECK (resolution_type IN (
        'adoption_review', 'field_diverged', 'path_conflict', 'payload_expired')),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'superseded')),
    choice TEXT,
    decision_digest TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
