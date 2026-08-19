# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The fixture walkthrough, end to end, with no credentials and no model.

Loading the fixtures alone leaves a store full of messages and no judgments,
which shows the collectors working and nothing else. The interesting claims —
that the top tier is reserved for what the user chose, that loud external
urgency cannot buy its way in, and that a correction outranks the memory — all
live downstream of a model turn.

So this script supplies that one turn from a file and runs everything after it
for real: `fixtures/envelopes/intake.json` stands in for what the model would
return, and the caps, the gate, the ranking, the writer, the correction path
and the re-ranking are the shipped code paths. What is canned is stated on
screen, because a walkthrough that blurs the two is worth less than no
walkthrough at all.

    export HERMES_HOME=$(mktemp -d)
    python3 profile/scripts/walkthrough.py --fixtures fixtures
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import correct
import load_fixtures
from _db import ensure_store, ledger_path
from apply_decisions import apply
from preferences import THRESHOLD, candidates, collect

RULE = "─" * 78


def _say(text: str = "") -> None:
    print(text, flush=True)


def _heading(number: int, text: str) -> None:
    _say()
    _say(RULE)
    _say(f"  {number}. {text}")
    _say(RULE)


def _open_rows(conn) -> list[tuple]:
    return conn.execute(
        "SELECT o.global_rank, o.priority, o.manual_priority, o.intent_gated, o.title"
        "  FROM obligations o WHERE o.status='open'"
        " ORDER BY o.global_rank").fetchall()


def _show_list(conn, note: str = "") -> None:
    rows = _open_rows(conn)
    if note:
        _say(note)
    _say()
    _say(f"  {'#':>2}  {'tier':<8} {'gate':<5} {'pinned':<7} title")
    for rank, priority, manual, gated, title in rows:
        _say(f"  {rank:>2}  {priority:<8} {'yes' if gated else '—':<5} "
             f"{(manual or '—'):<7} {title[:44]}")
    counts: dict[str, int] = {}
    for _, priority, *_rest in rows:
        counts[priority] = counts.get(priority, 0) + 1
    _say()
    _say("      tiers: " + ", ".join(f"{k}={counts.get(k, 0)}"
                                     for k in ("high", "medium", "low")))


def run(fixtures: Path) -> int:
    ensure_store()
    db = ledger_path()

    _heading(1, "Collect — fixture messages through the real normalizer")
    loaded = load_fixtures.load(fixtures)
    _say(f"  {loaded['added']} messages written to items, seed memory at "
         f"{Path(loaded['memory']).name}/")
    _say("  Nothing is judged yet. This is what ingestion alone produces.")

    _heading(2, "Judge — one canned model turn, then the real writer")
    envelope = json.loads((fixtures / "envelopes" / "intake.json").read_text())
    _say("  Envelope: fixtures/envelopes/intake.json (hand-written, stands in")
    _say("  for the model). Everything below it is the shipped code.")
    counts = apply(envelope)
    _say(f"  {json.dumps(counts)}")

    with sqlite3.connect(db) as conn:
        _show_list(conn)
        _say()
        _say("  Three rows passed the intent gate, so the top tier holds three —")
        _say("  not ten. It is never padded with whatever ranked next.")
        _say()
        _say("  The expense attestation is the row to watch. It is a real,")
        _say("  dated, mandatory deadline, and the model ranked it fourth. It")
        _say("  still cannot reach the top tier, because the user did not")
        _say("  choose it. A ranking without a memory cannot make that call.")

    _heading(3, "Correct — the user outranks the memory")
    _say("  The user decides the onboarding reply can wait, and drops it:")
    _say()
    _say("      python3 profile/scripts/correct.py priority msg-quiet-decay low")
    result = correct.set_priority("msg-quiet-decay", "low")
    _say(f"  {json.dumps(result)}")
    with sqlite3.connect(db) as conn:
        _show_list(conn)
        _say()
        _say("  The row passed the gate and still left the top tier, because a")
        _say("  pin outranks what the memory inferred. The whole open list was")
        _say("  re-ranked around it rather than the one row being nudged.")

    _heading(4, "Correct again — stop tracking a row entirely")
    _say("      python3 profile/scripts/correct.py ignore msg-cc-only \\")
    _say("          --reason 'copied, not asked'")
    correct.ignore("msg-cc-only", "copied, not asked")
    with sqlite3.connect(db) as conn:
        _show_list(conn)

    _heading(5, "Re-judge — a later pass cannot undo the correction")
    _say("  The scheduled review runs and the model, not knowing better, tries")
    _say("  to restore the onboarding reply to the top tier:")
    apply({"version": 1, "pass": "review", "decisions": [
        {"source_id": "msg-quiet-decay", "decision": "KEEP_OPEN", "rank": 1,
         "intent_gated": True, "title": "Reply to Sam on the onboarding revamp doc"}]})
    with sqlite3.connect(db) as conn:
        _show_list(conn)
        _say()
        _say("  The pin held. An agent pass never clears manual_priority, so a")
        _say("  correction survives every later re-judgment until the user")
        _say("  lifts it.")

    _heading(6, "Learn — corrections accumulate toward a policy")
    with sqlite3.connect(db) as conn:
        corrections = collect(conn)
        ready = candidates(corrections)
        _say(f"  user-authored corrections on record: {len(corrections)}")
        for c in corrections:
            _say(f"    · {c['event_type']:<18} {c['sender'] or c['source']}")
        _say()
        _say(f"  A rule is written only after {THRESHOLD} corrections agree.")
        _say(f"  Groups at or over that threshold right now: {len(ready)}")
        _say()
        _say("  Two corrections do not make a policy, and the walkthrough stops")
        _say("  honestly short of one. On a real mailbox the third ignore of the")
        _say("  same sender writes a line into workspace/policy/preferences.md,")
        _say("  which intake and review then read as a prior. A run of ignores")
        _say("  aimed at one sender never widens into a rule about their whole")
        _say("  mail domain — colleagues share the user's own domain, so that")
        _say("  needs corroboration from a second sender.")

    _heading(7, "Verify — the memory checks itself")
    _say("      python3 profile/scripts/memory_check.py")
    _say("  Runs the same invariants the scheduled repair job uses: index")
    _say("  consistency, resolvable links, required frontmatter, provenance,")
    _say("  decay and page-size ceilings.")
    _say()
    _say(RULE)
    _say(f"  Store: {db}")
    _say("  Re-run any step; the writer is keyed on source_id and is idempotent.")
    _say(RULE)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"),
                        help="path to the fixtures directory (default: ./fixtures)")
    args = parser.parse_args(argv)
    if not (args.fixtures / "envelopes" / "intake.json").exists():
        print(f"no fixtures at {args.fixtures}; run from the recipe root or pass "
              f"--fixtures", file=sys.stderr)
        return 2
    return run(args.fixtures)


if __name__ == "__main__":
    raise SystemExit(main())
