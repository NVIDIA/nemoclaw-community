# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cron pre-step for the intake pass.

Runs the collectors, then hands the agent a slice of unjudged items. When
there is nothing new it emits `{"wakeAgent": false}`, which Hermes treats as a
signal to skip the agent turn entirely — so a quiet half-hour costs no tokens
at all rather than paying a model call to be told there is no work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _db import ensure_store, write_txn

HERE = Path(__file__).resolve().parent
SLICE = int(os.environ.get("INTAKE_SLICE", "25"))


def collect() -> dict[str, object]:
    """Run whichever collectors are present and configured.

    A collector that is absent is not an error. The store and the schedule ship
    before the connectors do, and a reader who never connects a source still
    gets a working intake pass over whatever is already in the store.
    """
    results: dict[str, object] = {}
    for script in ("ingest_graph.py", "ingest_slack.py"):
        path = HERE / script
        if not path.exists():
            results[script] = {"absent": True}
            continue
        proc = subprocess.run([sys.executable, str(path)],
                              capture_output=True, text=True)
        try:
            results[script] = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            # A collector that fails must not take the whole tick down; the
            # slice below still has yesterday's unjudged items to work on.
            results[script] = {"error": (proc.stderr or "").strip()[:200]}
    return results


def main() -> int:
    ensure_store()
    collected = collect()

    with write_txn() as conn:
        rows = conn.execute(
            "SELECT source_id, source, scope, event_at, sender, subject, body,"
            "       addressing, unread"
            "  FROM items WHERE state='pending'"
            " ORDER BY event_at LIMIT ?", (SLICE,)).fetchall()
        open_rows = conn.execute(
            "SELECT o.source_id, o.title, o.status FROM obligations o"
            " WHERE o.status='open' ORDER BY o.global_rank LIMIT 40").fetchall()
        recent_closed = conn.execute(
            "SELECT o.title, o.status FROM obligations o"
            " WHERE o.status IN ('done','ignored')"
            " ORDER BY o.updated_at DESC LIMIT 20").fetchall()

    cols = ("source_id", "source", "scope", "event_at", "sender", "subject",
            "body", "addressing", "unread")
    payload = {
        "collected": collected,
        "slice": [dict(zip(cols, r)) for r in rows],
        "open_obligations": [{"source_id": r[0], "title": r[1]} for r in open_rows],
        "recently_resolved": [{"title": r[0], "status": r[1]} for r in recent_closed],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not rows:
        print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
