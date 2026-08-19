# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The fixture walkthrough, end to end, with no credentials and no model.

Loading the fixtures alone leaves a store full of messages and no judgments,
which shows the collectors working and nothing else. The interesting claims —
that the top tier is reserved for what the user chose, that loud external
urgency cannot buy its way in, and that a correction outranks the memory — all
live downstream of a model turn.

So this script supplies those turns and runs everything after them for real.
Two turns are recorded: the intake judgment in
`fixtures/envelopes/intake.json`, and the scheduled re-judgment written inline
in step 5. The caps, the ranking, the writer, the correction path and the
re-ranking are the shipped code paths.

The gate verdict on each row is part of the recorded intake turn, because
deciding it means reading the memory, which needs a model. So this run does not
show the memory producing those verdicts; it shows everything they feed into,
and prints the same batch with the verdicts withheld so the reservation the
gate buys is visible. What is recorded is stated on screen, because a
walkthrough that blurs the two is worth less than no walkthrough at all.

    export HERMES_HOME=$(mktemp -d)
    python3 profile/scripts/walkthrough.py --fixtures fixtures
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import correct
import load_fixtures
from _db import ensure_store, ledger_path
from apply_decisions import apply
from memory_check import check_all
from ranking import rank_population
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

    # A second run against the same profile home inherits the first run's
    # corrections, so the narration below — written for a first run — would
    # describe numbers the tables no longer show. Refuse rather than print a
    # commentary that contradicts its own output.
    with sqlite3.connect(db) as conn:
        already = conn.execute("SELECT COUNT(*) FROM obligations").fetchone()[0]
    if already:
        _say(f"This profile home already holds {already} obligations from an")
        _say("earlier run, whose corrections would still be in force. The")
        _say("walkthrough narrates a first run, so it would describe numbers")
        _say("its own tables no longer show. Point HERMES_HOME at a fresh")
        _say("directory and run it again:")
        _say()
        _say("    export HERMES_HOME=$(mktemp -d)")
        return 2

    _heading(1, "Collect — fixture messages through the real normalizer")
    loaded = load_fixtures.load(fixtures)
    if loaded.get("seeded"):
        _say(f"  {loaded['added']} messages written to items, seed memory at "
             f"{Path(loaded['memory']).name}/")
    else:
        # This walkthrough is documentation that executes, so it must not
        # announce a seed memory that a fixture set did not ship.
        _say(f"  {loaded['added']} messages written to items. This fixture set "
             "ships no seed memory.")
    _say("  Nothing is judged yet. This is what ingestion alone produces.")

    _heading(2, "Judge — the first canned model turn, then the real writer")
    envelope = json.loads((fixtures / "envelopes" / "intake.json").read_text())
    _say("  Envelope: fixtures/envelopes/intake.json (hand-written, stands in")
    _say("  for the model). Everything below it is the shipped code.")
    _say()
    _say("  Note what is recorded here and what is not. The gate verdict on")
    _say("  each row — whether the memory shows the user chose this work — is")
    _say("  part of the envelope, because deciding it needs a model reading")
    _say("  the memory. Deleting the seed memory does not change the tiers")
    _say("  below. What the tiers below do show is everything the verdicts")
    _say("  feed into: the caps, the reservation, the cascade and the writer.")
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
        _say()
        _say("  Here is the same batch with the gate verdicts withheld — what")
        _say("  this run would produce if the memory held nothing the user had")
        _say("  chosen. Same rows, same shipped ranking code, one input less:")
        rows = [
            {"source_id": r[0], "intent_gated": bool(r[1]),
             "manual_priority": r[2], "batch_rank": r[3]}
            for r in conn.execute(
                "SELECT source_id, intent_gated, manual_priority, batch_rank"
                "  FROM obligations WHERE status='open'")
        ]
        ungated = rank_population([{**r, "intent_gated": False} for r in rows])
        tally = {tier: sum(1 for x in ungated if x["priority"] == tier)
                 for tier in ("high", "medium", "low")}
        _say(f"      tiers without the gate: " +
             ", ".join(f"{k}={v}" for k, v in tally.items()))
        _say("  The top tier empties. It is reserved rather than filled, so")
        _say("  with nothing to reserve it for it stays empty instead of")
        _say("  handing the place to whatever ranked next.")

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

    _heading(5, "Re-judge — the second canned turn cannot undo the correction")
    _say("  The scheduled review runs. This is the other recorded turn: a")
    _say("  review envelope, written inline below rather than in fixtures/,")
    _say("  in which the model does not know about the pin and tries to")
    _say("  restore the onboarding reply to the top tier.")
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
    _say("  The same invariants the scheduled repair job uses: index")
    _say("  consistency, resolvable links, required frontmatter, provenance,")
    _say("  decay and page-size ceilings.")
    _say()
    root = Path(loaded["memory"])
    findings = check_all(root, date.today())
    _say(f"  clean: {not findings}   findings: {len(findings)}")
    for f in findings:
        _say(f"    · {f.kind:<20} {f.path}: {f.detail}")
    if findings and all(f.kind == "stale" for f in findings):
        _say()
        _say("  That is the decay rule firing, not a broken fixture. The loader")
        _say("  stamps the seed memory as of the day it ran, and the attention")
        _say("  page is marked `decay: daily`, so it ages out one day later —")
        _say("  which is the point: a priority nobody has confirmed since should")
        _say("  stop being treated as current. On a live system the repair job")
        _say("  refreshes the page or retires it.")
    _say()
    _say("  Break one on purpose — the check has to be able to fail, or it is")
    _say("  telling you nothing:")
    # Reachable with a fixture directory that ships no seed memory; say so
    # rather than raising StopIteration out of a demonstration step.
    person = next((root / "people").glob("*.md"), None)
    if person is None:
        _say("      no person page to break — this fixture set ships no seed")
        _say("      memory, so this demonstration is skipped.")
    else:
        original = person.read_text()
        try:
            person.write_text(original.replace("name:", "nome:", 1))
            broken = check_all(root, date.today())
        finally:
            person.write_text(original)
        _say(f"      after removing `name` from people/{person.name}: "
             f"{len(broken)} finding(s)")
        for f in broken:
            _say(f"    · {f.kind:<20} {f.path}: {f.detail}")
        _say("  (restored)")

    _say()
    _say(RULE)
    _say(f"  Store: {db}")
    _say("  Each script is idempotent on its own inputs, but this walkthrough")
    _say("  is not: a second run inherits the corrections the first one made.")
    _say("  Use a fresh HERMES_HOME to see it from the start again.")
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
