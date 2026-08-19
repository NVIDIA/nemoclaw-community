# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The user's writer.

Corrections come from the user, so they cannot come from the model. The skills
forbid the agent from touching `manual_priority` or from writing an `ignored`
event, for the same reason `preference-update` refuses to read agent-authored
rows: a system that can manufacture its own evidence will eventually believe
something nobody told it.

That leaves the user needing a way in, which is this script. It is the only
thing that writes `actor='user'`, and it is what the conversational surface
calls when the user says "stop showing me these" or "this one is not urgent".

    python3 correct.py ignore <source_id> [--reason "..."]
    python3 correct.py priority <source_id> high|medium|low
    python3 correct.py unignore <source_id>

Every correction re-ranks the open population before it commits, so the effect
is visible on the next read rather than at the next scheduled pass.
"""

from __future__ import annotations

import argparse
import json
import sys

from _db import ensure_store, write_txn
from ranking import rank_population

TIERS = ("high", "medium", "low")


class InvalidTransition(ValueError):
    """The correction does not apply to an obligation in this state."""


def _refuse_if_closed(source_id: str, status: str, action: str) -> None:
    """A completed obligation is history, and history is not a preference.

    Every command here writes evidence that later shapes the ranking, so a
    command that silently rewrote a `done` row would turn a finished piece of
    work into a standing instruction — and would destroy the completed record
    on the way. The completed view exists to be read back.
    """
    if status == "done":
        raise InvalidTransition(
            f"{source_id} is done; {action} does not apply to a completed "
            "obligation. Reopen it through a judging pass if it is not "
            "actually finished.")


def _row(conn, source_id: str):
    got = conn.execute(
        "SELECT id, status, priority, manual_priority, global_rank"
        "  FROM obligations WHERE source_id=?", (source_id,)).fetchone()
    if got is None:
        raise LookupError(f"no obligation for source_id {source_id!r}")
    return got


def _log(conn, obligation_id: str, event_type: str, before, after,
         actor: str = "user") -> None:
    """Record one event.

    The default actor is the user, because this module exists to record what
    the user did. Rows merely displaced by that decision are logged as `agent`:
    the user chose one row, not the reshuffle underneath it, and
    `preferences.collect` counts only user-authored rows as evidence.
    """
    conn.execute(
        "INSERT INTO events(obligation_id, event_type, actor, before_json, after_json)"
        " VALUES (?,?,?,?,?)",
        (obligation_id, event_type, actor, json.dumps(before), json.dumps(after)))


def _rerank_open(conn, corrected_id: str | None = None) -> None:
    """Re-rank every open row, honouring manual priority, and audit the moves.

    A correction is worth nothing if the list it corrects is stale, and the
    caps are a property of the whole open population, so this reuses the same
    ranking the agent's writer does rather than nudging one row.

    Correcting one row moves others. Ignoring the row at position one pulls
    every row below it up, and those rows are not named by the command that
    moved them — so an audit built from the command alone records nothing, and
    the store cannot explain why they moved. `corrected_id` is the row the user
    acted on directly; it already has its own correction event and is not
    audited twice here.
    """
    rows = [
        {"id": r[0], "source_id": r[1], "intent_gated": bool(r[2]),
         "manual_priority": r[3], "batch_rank": r[4], "was": (r[5], r[6])}
        for r in conn.execute(
            "SELECT id, source_id, intent_gated, manual_priority, batch_rank,"
            "       priority, global_rank FROM obligations WHERE status='open'")
    ]
    conn.execute("UPDATE obligations SET global_rank=NULL WHERE status='open'")
    for row in rank_population(rows):
        conn.execute("UPDATE obligations SET priority=?, global_rank=? WHERE id=?",
                     (row["priority"], row["global_rank"], row["id"]))
        was = row["was"]
        if row["id"] == corrected_id or (row["priority"], row["global_rank"]) == was:
            continue
        _log(conn, row["id"], "reranked",
             {"priority": was[0], "rank": was[1]},
             {"priority": row["priority"], "rank": row["global_rank"]},
             actor="agent")


def ignore(source_id: str, reason: str | None = None) -> dict:
    """Close a row as unwanted and record that the user is the one who said so.

    Repeating it is a no-op. Only a state transition is evidence: a retried
    command, a double-click, or a re-run script is one decision, and counting
    it three times is how three identical rows reach the preference threshold
    and mint a rule the user never asked for.
    """
    with write_txn() as conn:
        oid, status, priority, _, rank = _row(conn, source_id)
        _refuse_if_closed(source_id, status, "ignore")
        if status == "ignored":
            return {"source_id": source_id, "status": "ignored", "changed": False}
        conn.execute("UPDATE obligations SET status='ignored' WHERE id=?", (oid,))
        _log(conn, oid, "ignored",
             {"status": status, "priority": priority, "rank": rank},
             {"status": "ignored", "reason": reason})
        _rerank_open(conn, corrected_id=oid)
    return {"source_id": source_id, "status": "ignored", "changed": True}


def unignore(source_id: str) -> dict:
    """Reopen a row. The original correction stays in the log.

    A no-op on a row that is already open, for the same reason `ignore` is.
    """
    with write_txn() as conn:
        oid, status, priority, _, rank = _row(conn, source_id)
        if status == "open":
            return {"source_id": source_id, "status": "open", "changed": False}
        _refuse_if_closed(source_id, status, "restore")
        # Clear the position on the way back in. The row kept the rank it held
        # when it was ignored, and the open list has moved on since, so
        # reopening it with that rank trips the uniqueness index against
        # whichever row holds the position now. `_rerank_open` assigns it a
        # real one a moment later.
        conn.execute("UPDATE obligations SET status='open', global_rank=NULL"
                     " WHERE id=?", (oid,))
        _log(conn, oid, "restored", {"status": status}, {"status": "open"})
        _rerank_open(conn, corrected_id=oid)
    return {"source_id": source_id, "status": "open", "changed": True}


def set_priority(source_id: str, tier: str) -> dict:
    """Pin a tier. The agent may re-rank around it but never clears it.

    Re-pinning the tier a row already carries is a no-op, so a repeated command
    cannot turn one preference into several pieces of evidence.
    """
    if tier not in TIERS:
        raise ValueError(f"priority must be one of {TIERS}, got {tier!r}")
    with write_txn() as conn:
        oid, status, priority, manual, rank = _row(conn, source_id)
        _refuse_if_closed(source_id, status, "a priority override")
        if status != "open":
            raise InvalidTransition(
                f"{source_id} is {status}; a priority override applies to the "
                "open list. Restore it first.")
        if manual == tier:
            return {"source_id": source_id, "manual_priority": tier,
                    "priority": priority, "global_rank": rank, "changed": False}
        conn.execute("UPDATE obligations SET manual_priority=? WHERE id=?", (tier, oid))
        _log(conn, oid, "priority_override",
             {"priority": priority, "manual_priority": manual, "rank": rank},
             {"manual_priority": tier})
        _rerank_open(conn, corrected_id=oid)
        new = conn.execute(
            "SELECT priority, global_rank FROM obligations WHERE id=?", (oid,)).fetchone()
    return {"source_id": source_id, "manual_priority": tier,
            "priority": new[0], "global_rank": new[1], "changed": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_ignore = sub.add_parser("ignore", help="stop tracking this obligation")
    p_ignore.add_argument("source_id")
    p_ignore.add_argument("--reason", default=None)

    sub.add_parser("unignore", help="reopen an ignored obligation").add_argument("source_id")

    p_priority = sub.add_parser("priority", help="pin a tier for this obligation")
    p_priority.add_argument("source_id")
    p_priority.add_argument("tier", choices=TIERS)

    args = parser.parse_args(argv)
    ensure_store()
    try:
        if args.command == "ignore":
            out = ignore(args.source_id, args.reason)
        elif args.command == "unignore":
            out = unignore(args.source_id)
        else:
            out = set_priority(args.source_id, args.tier)
    except (LookupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
