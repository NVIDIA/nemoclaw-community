# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cron pre-step for the review pass.

Selects the stalest open obligations — never reviewed first, then longest
since — so re-judgment is driven by time rather than by new mail arriving. A
week with no incoming messages still re-ranks, which is exactly when a
shortlist is most likely to have gone quietly wrong.
"""

from __future__ import annotations

import json
import os

from _db import ensure_store, write_txn

BATCH = int(os.environ.get("REVIEW_BATCH", "15"))


def main() -> int:
    ensure_store()

    with write_txn() as conn:
        rows = conn.execute(
            "SELECT o.source_id, o.title, o.context, o.urgency_reason, o.kind,"
            "       o.est_effort, o.priority, o.manual_priority, o.global_rank,"
            "       o.intent_gated, o.snooze_count, o.reviewed_at,"
            "       i.event_at, i.sender, i.subject, i.addressing, i.thread_ref"
            "  FROM obligations o JOIN items i ON i.source_id = o.source_id"
            " WHERE o.status='open'"
            "   AND (o.snoozed_until IS NULL"
            "        OR o.snoozed_until <= strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
            " ORDER BY o.reviewed_at IS NOT NULL, o.reviewed_at"
            " LIMIT ?", (BATCH,)).fetchall()

    cols = ("source_id", "title", "context", "urgency_reason", "kind",
            "est_effort", "priority", "manual_priority", "global_rank",
            "intent_gated", "snooze_count", "reviewed_at",
            "source_event_at", "sender", "subject", "addressing", "thread_ref")
    print(json.dumps({"batch": [dict(zip(cols, r)) for r in rows]},
                     ensure_ascii=False, indent=2))

    if not rows:
        print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
