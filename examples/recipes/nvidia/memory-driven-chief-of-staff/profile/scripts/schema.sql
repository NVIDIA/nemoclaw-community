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
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '4');


-- ---------------------------------------------------------------------------
-- 1) items — every inbound message we have looked at.
--    Intake is idempotent on source_id, so re-reading a source is safe.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
    -- Email: the Graph message id. Slack: "<channel_id>:<ts>", because a
    -- Slack timestamp is only unique within its channel.
    source_id   TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('email','slack')),
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
    state_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Intake selector reads this: oldest pending first.
CREATE INDEX IF NOT EXISTS idx_items_pending ON items(state, event_at);
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
