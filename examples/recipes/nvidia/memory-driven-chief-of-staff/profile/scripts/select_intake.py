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

def bounded_int(name: str, default: int, *, maximum: int) -> int:
    """Read a positive, bounded integer from the environment.

    `LIMIT` takes whatever it is given, and SQLite reads a negative one as no
    limit at all — so `INTAKE_SLICE=-1` handed the model every pending row in
    the store, silently defeating the bound this recipe is built on. Zero is
    just as wrong in the other direction: the job wakes, reports work, and
    offers nothing. Malformed text used to raise during import, before any
    error message could explain which variable was at fault.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"{name} must be a whole number between 1 and {maximum}; got {raw!r}")
    if value < 1 or value > maximum:
        raise SystemExit(
            f"{name} must be between 1 and {maximum}; got {value}")
    return value


HERE = Path(__file__).resolve().parent
MAX_SLICE = 200
SLICE = None  # resolved in main(); see bounded_int


def collect() -> tuple[dict[str, object], bool]:
    """Run whichever collectors are present, and report whether any failed.

    A collector that is absent is not an error. The store and the schedule ship
    before the connectors do, and a reader who never connects a source still
    gets a working intake pass over whatever is already in the store.

    A collector that *fails* is a different thing, and it must be visible. The
    exit code is what says so: a connector whose credential expired writes to
    stderr and exits non-zero while printing nothing, and `json.loads("" or
    "{}")` turns that into an empty success. Combined with the idle gate below
    it produced the worst failure this design can have — a token that stopped
    working, a tick that skipped the agent, and nothing anywhere saying so,
    every half hour.

    What a failure reports is deliberately narrow. This function's stdout is
    the scheduled agent's prompt, and a collector's stderr is arbitrary text
    from a subprocess that talks to a mail or chat API: a traceback carrying a
    bearer token, a request URL with a signature in the query string, a
    response body full of someone's messages. Truncating that to a couple of
    hundred characters bounds its length, not its content — the first two
    hundred characters of a traceback are exactly where the request line is.

    So the prompt gets a stable error class and an exit code, which is all the
    agent can act on anyway, and the operator gets the detail on this
    process's own stderr, where cron writes it to a local log instead of
    sending it to an inference provider.

    Returns the per-collector results and a flag: true if any of them failed.
    """
    results: dict[str, object] = {}
    failed = False
    for script in ("ingest_graph.py", "ingest_slack.py"):
        path = HERE / script
        if not path.exists():
            results[script] = {"absent": True}
            continue
        proc = subprocess.run([sys.executable, str(path)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            failed = True
            results[script] = {"failed": True, "exit_code": proc.returncode,
                               "error_class": "nonzero_exit"}
            _report(script, proc.stderr)
            continue
        try:
            results[script] = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            failed = True
            results[script] = {"failed": True, "exit_code": proc.returncode,
                               "error_class": "unreadable_output"}
            _report(script, proc.stderr)
    return results, failed


def _report(script: str, stderr: str | None) -> None:
    """Put a failing collector's own output where an operator can read it.

    Not on stdout: that is the agent's prompt. This goes to stderr, which the
    scheduler captures into the job's local log.
    """
    detail = (stderr or "").strip()
    if detail:
        print(f"{script}: {detail}", file=sys.stderr)


def main() -> int:
    global SLICE
    SLICE = bounded_int("INTAKE_SLICE", 25, maximum=MAX_SLICE)
    ensure_store()
    collected, collector_failed = collect()

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

    # Wake on a collector failure even with nothing to judge. The gate exists
    # to make an idle tick free, not to make a broken one quiet.
    if not rows and not collector_failed:
        print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
