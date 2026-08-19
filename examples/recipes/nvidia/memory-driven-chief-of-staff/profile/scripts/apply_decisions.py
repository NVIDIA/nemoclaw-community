# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The only writer.

The model never emits SQL. It returns one decision envelope on stdin and this
script turns it into rows, in a single transaction, together with the cursor
that covers them.

Envelope (stdin, JSON):

    {
      "version": 1,
      "pass": "intake" | "review",
      "decisions": [
        {
          "source_id": "AAMkAD...",       # required, matches items.source_id
          "decision": "CREATE" | "KEEP_OPEN" | "MARK_DONE" | "SKIP",
          "rank": 1,                       # required unless SKIP/MARK_DONE
          "intent_gated": true,            # required unless SKIP/MARK_DONE
          "title": "Reply to the Q3 capacity thread",
          "context": "...",                # <= 3 short bullets
          "urgency_reason": "...",
          "kind": "response" | "action" | null,
          "est_effort": "minutes" | "hours" | "day" | "multi_day" | null
        }
      ],
      "cursor": {"source": "email", "scope": "inbox", "value": "<opaque>"}
    }

`SKIP` marks an item as not worth tracking — a terminal state, so it is never
re-judged. `MARK_DONE` closes an obligation and keeps its tier untouched so the
completed view stays auditable.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from _db import ensure_store, write_txn
from ranking import RankedRow, assign_priorities

VALID_DECISIONS = {"CREATE", "KEEP_OPEN", "MARK_DONE", "SKIP"}
VALID_KIND = {"response", "action", None}
VALID_EFFORT = {"minutes", "hours", "day", "multi_day", None}


def _validate(env: dict[str, Any]) -> list[dict[str, Any]]:
    if env.get("version") != 1:
        raise ValueError(f"unsupported envelope version: {env.get('version')!r}")
    decisions = env.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("envelope.decisions must be a list")

    seen: set[str] = set()
    for d in decisions:
        sid = d.get("source_id")
        if not sid:
            raise ValueError("every decision needs a source_id")
        if sid in seen:
            raise ValueError(f"duplicate source_id in envelope: {sid}")
        seen.add(sid)
        if d.get("decision") not in VALID_DECISIONS:
            raise ValueError(f"{sid}: bad decision {d.get('decision')!r}")
        if d.get("kind") not in VALID_KIND:
            raise ValueError(f"{sid}: bad kind {d.get('kind')!r}")
        if d.get("est_effort") not in VALID_EFFORT:
            raise ValueError(f"{sid}: bad est_effort {d.get('est_effort')!r}")
        if d["decision"] in {"CREATE", "KEEP_OPEN"}:
            if not isinstance(d.get("rank"), int):
                raise ValueError(f"{sid}: {d['decision']} needs an integer rank")
            if not isinstance(d.get("intent_gated"), bool):
                raise ValueError(f"{sid}: {d['decision']} needs a boolean intent_gated")
            if not d.get("title"):
                raise ValueError(f"{sid}: {d['decision']} needs a title")
    return decisions


def _log(conn, obligation_id: str, event_type: str, before, after, actor="agent") -> None:
    conn.execute(
        "INSERT INTO events(obligation_id, event_type, actor, before_json, after_json)"
        " VALUES (?,?,?,?,?)",
        (obligation_id, event_type, actor,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None),
    )


def apply(env: dict[str, Any]) -> dict[str, int]:
    decisions = _validate(env)
    ranked_input = [d for d in decisions if d["decision"] in {"CREATE", "KEEP_OPEN"}]
    ranked_input.sort(key=lambda d: d["rank"])

    # Tier assignment is arithmetic, so it happens here rather than in the prompt.
    tiers = {
        r.source_id: r
        for r in assign_priorities(
            RankedRow(source_id=d["source_id"], intent_gated=d["intent_gated"])
            for d in ranked_input
        )
    }

    counts = {"created": 0, "updated": 0, "done": 0, "skipped": 0}

    with write_txn() as conn:
        for d in decisions:
            sid, verdict = d["source_id"], d["decision"]

            if verdict == "SKIP":
                conn.execute(
                    "UPDATE items SET state='skipped',"
                    " state_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE source_id=?",
                    (sid,))
                counts["skipped"] += 1
                continue

            if verdict == "MARK_DONE":
                row = conn.execute(
                    "SELECT id, status, urgency_reason FROM obligations WHERE source_id=?",
                    (sid,)
                ).fetchone()
                if row:
                    oid, old_status, old_reason = row
                    # Tier is deliberately left alone: the completed view is an
                    # audit trail, not a queue. The closing reason IS persisted —
                    # a row must never close without the user being able to see
                    # why, so it overwrites urgency_reason when supplied.
                    reason = d.get("urgency_reason") or old_reason
                    conn.execute(
                        "UPDATE obligations SET status='done', urgency_reason=? WHERE id=?",
                        (reason, oid))
                    _log(conn, oid, "completed",
                         {"status": old_status, "urgency_reason": old_reason},
                         {"status": "done", "urgency_reason": reason})
                    counts["done"] += 1
                continue

            t = tiers[sid]
            conn.execute(
                "UPDATE items SET state='judged',"
                " state_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE source_id=?",
                (sid,))

            existing = conn.execute(
                "SELECT id, priority, global_rank FROM obligations WHERE source_id=?", (sid,)
            ).fetchone()

            if existing is None:
                oid = uuid.uuid4().hex[:12]
                conn.execute(
                    "INSERT INTO obligations(id, source_id, title, context, urgency_reason,"
                    " kind, est_effort, priority, global_rank, intent_gated, reviewed_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (oid, sid, d["title"], d.get("context"), d.get("urgency_reason"),
                     d.get("kind"), d.get("est_effort"), t.priority, t.global_rank,
                     int(d["intent_gated"])))
                _log(conn, oid, "created", None,
                     {"priority": t.priority, "rank": t.global_rank})
                counts["created"] += 1
            else:
                oid, old_priority, old_rank = existing
                # manual_priority is user feedback: never copied blindly into
                # `priority`, and never cleared by an agent pass.
                conn.execute(
                    "UPDATE obligations SET title=?, context=?, urgency_reason=?, kind=?,"
                    " est_effort=?, priority=?, global_rank=?, intent_gated=?,"
                    " reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (d["title"], d.get("context"), d.get("urgency_reason"), d.get("kind"),
                     d.get("est_effort"), t.priority, t.global_rank,
                     int(d["intent_gated"]), oid))
                if (old_priority, old_rank) != (t.priority, t.global_rank):
                    _log(conn, oid, "reranked",
                         {"priority": old_priority, "rank": old_rank},
                         {"priority": t.priority, "rank": t.global_rank})
                counts["updated"] += 1

        cur = env.get("cursor")
        if cur:
            # Same transaction as the rows it covers.
            conn.execute(
                "INSERT INTO cursors(source, scope, cursor) VALUES (?,?,?)"
                " ON CONFLICT(source, scope) DO UPDATE SET cursor=excluded.cursor,"
                " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (cur["source"], cur["scope"], cur["value"]))

    return counts


def main() -> int:
    ensure_store()
    try:
        env = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"malformed envelope: {exc}", file=sys.stderr)
        return 2
    try:
        counts = apply(env)
    except ValueError as exc:
        print(f"rejected envelope: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
