#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SQLite-backed task store & queue for deepagents-worker.
Supports atomic task claiming, status updates, retries, cancellation, tool-call
observability, and TTL cleanup.
"""
import datetime
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import timedelta
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _iso_now() -> str:
    return _utcnow().isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


class TaskStore:
    VALID_TOOL_PROFILES = {"research", "minimal"}

    def __init__(self, state_dir: str, ttl_hours: int = 168):
        self.state_dir = state_dir
        self.ttl_hours = ttl_hours
        os.makedirs(self.state_dir, exist_ok=True)
        self.db_path = os.path.join(self.state_dir, "tasks.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _add_column_if_missing(self, conn: sqlite3.Connection, column_sql: str) -> None:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column_sql}")
        except sqlite3.OperationalError:
            pass

    def _init_db(self):
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    timeout_ms INTEGER NOT NULL,
                    depth TEXT NOT NULL DEFAULT 'standard',
                    rubric TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 2,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    last_activity_at TEXT,
                    tool_profile TEXT NOT NULL DEFAULT 'research',
                    tool_call_budget INTEGER,
                    tool_calls TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            self._add_column_if_missing(conn, "depth TEXT NOT NULL DEFAULT 'standard'")
            self._add_column_if_missing(conn, "rubric TEXT")
            self._add_column_if_missing(conn, "retry_count INTEGER NOT NULL DEFAULT 0")
            self._add_column_if_missing(conn, "max_retries INTEGER NOT NULL DEFAULT 2")
            self._add_column_if_missing(conn, "next_attempt_at TEXT")
            self._add_column_if_missing(conn, "last_error TEXT")
            self._add_column_if_missing(conn, "last_activity_at TEXT")
            self._add_column_if_missing(conn, "tool_profile TEXT NOT NULL DEFAULT 'research'")
            self._add_column_if_missing(conn, "tool_call_budget INTEGER")
            self._add_column_if_missing(conn, "tool_calls TEXT NOT NULL DEFAULT '[]'")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)"
            )
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_status_next_attempt ON tasks(status, next_attempt_at, created_at)"
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def _normalize_task(self, row: sqlite3.Row) -> Dict[str, Any]:
        task = dict(row)
        task["retry_count"] = int(task.get("retry_count") or 0)
        task["max_retries"] = int(task.get("max_retries") or 0)
        task["timeout_ms"] = int(task.get("timeout_ms") or 0)
        if task.get("tool_profile") not in self.VALID_TOOL_PROFILES:
            task["tool_profile"] = "research"
        raw_tool_calls = task.get("tool_calls")
        try:
            tool_calls = json.loads(raw_tool_calls) if raw_tool_calls else []
        except (TypeError, json.JSONDecodeError):
            tool_calls = []
        if not isinstance(tool_calls, list):
            tool_calls = []
        task["tool_calls"] = tool_calls
        tool_call_count: Dict[str, int] = {}
        for entry in tool_calls:
            tool_name = entry.get("tool")
            if tool_name:
                tool_call_count[tool_name] = tool_call_count.get(tool_name, 0) + 1
        task["tool_call_count"] = tool_call_count
        return task

    def enqueue(
        self,
        prompt: str,
        model: str = "gpt-5",
        mode: str = "live",
        timeout_ms: int = 600000,
        depth: str = "standard",
        rubric: Optional[str] = None,
        max_retries: int = 2,
        tool_profile: str = "research",
        tool_call_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _iso_now()
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, prompt, model, mode, status, created_at, timeout_ms, depth, rubric,
                    retry_count, max_retries, tool_profile, tool_call_budget, tool_calls
                )
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, 0, ?, ?, ?, '[]')
                """,
                (
                    task_id,
                    prompt,
                    model,
                    mode,
                    now,
                    timeout_ms,
                    depth,
                    rubric,
                    max_retries,
                    tool_profile,
                    tool_call_budget,
                ),
            )
            conn.commit()
        return self.get_task(task_id)

    def recover_inflight(self) -> Dict[str, int]:
        """Resolve tasks that cannot still have a live executor after restart."""
        now = _iso_now()
        with closing(self._get_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cancelled = conn.execute(
                """
                UPDATE tasks
                SET status = 'cancelled',
                    error = 'cancelled during worker restart',
                    completed_at = ?,
                    next_attempt_at = NULL
                WHERE status = 'cancelling'
                """,
                (now,),
            ).rowcount
            failed = conn.execute(
                """
                UPDATE tasks
                SET status = 'failed',
                    error = 'worker restarted before execution completed',
                    completed_at = ?,
                    next_attempt_at = NULL
                WHERE status = 'running'
                """,
                (now,),
            ).rowcount
            conn.commit()
        return {"failed": failed, "cancelled": cancelled}

    def claim_next(self) -> Optional[Dict[str, Any]]:
        now = _iso_now()
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                """
                SELECT task_id
                FROM tasks
                WHERE status = 'queued'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            task_id = row["task_id"]
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'running', claimed_at = ?, last_activity_at = ?
                WHERE task_id = ? AND status = 'queued'
                """,
                (now, now, task_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                return self.get_task(task_id)
        return None

    def mark_for_retry(
        self,
        task_id: str,
        retry_count: int,
        next_attempt_at: str,
        last_error: str,
    ) -> bool:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'queued',
                    retry_count = ?,
                    next_attempt_at = ?,
                    last_error = ?,
                    claimed_at = NULL
                WHERE task_id = ? AND status = 'running'
                """,
                (retry_count, next_attempt_at, last_error, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_cancelling(self, task_id: str) -> Optional[str]:
        with closing(self._get_connection()) as conn:
            row = conn.execute(
                "SELECT status FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            status = row["status"]
            now = _iso_now()
            if status == "queued":
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelled', error = 'cancelled by caller', completed_at = ?
                    WHERE task_id = ?
                    """,
                    (now, task_id),
                )
            elif status == "running":
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelling', error = 'cancelled by caller'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
            conn.commit()
            return status

    def update_result(
        self,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        now = _iso_now()
        terminal_statuses = {"completed", "failed", "cancelled"}
        completed_at = now if status in terminal_statuses else None
        status_guard = " AND status = 'running'" if status in {"completed", "failed"} else ""
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                f"""
                UPDATE tasks
                SET status = ?,
                    result = COALESCE(?, result),
                    error = ?,
                    completed_at = ?,
                    next_attempt_at = CASE WHEN ? IN ('completed', 'failed', 'cancelled') THEN NULL ELSE next_attempt_at END
                WHERE task_id = ?{status_guard}
                """,
                (status, result, error, completed_at, status, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def touch_activity(self, task_id: str, when: Optional[str] = None) -> bool:
        when = when or _iso_now()
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                "UPDATE tasks SET last_activity_at = ? WHERE task_id = ?",
                (when, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def append_tool_call(self, task_id: str, entry: Dict[str, Any]) -> bool:
        with closing(self._get_connection()) as conn:
            row = conn.execute(
                "SELECT tool_calls FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return False
            raw = row["tool_calls"] or "[]"
            try:
                tool_calls = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                tool_calls = []
            if not isinstance(tool_calls, list):
                tool_calls = []
            tool_calls.append(entry)
            cursor = conn.execute(
                "UPDATE tasks SET tool_calls = ? WHERE task_id = ?",
                (json.dumps(tool_calls), task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return self._normalize_task(row)
        return None

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [self._normalize_task(r) for r in cursor.fetchall()]

    def cleanup_expired(self) -> int:
        cutoff = (_utcnow() - timedelta(hours=self.ttl_hours)).isoformat()
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                """
                DELETE FROM tasks
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND completed_at IS NOT NULL
                  AND completed_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
