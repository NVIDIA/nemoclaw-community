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
