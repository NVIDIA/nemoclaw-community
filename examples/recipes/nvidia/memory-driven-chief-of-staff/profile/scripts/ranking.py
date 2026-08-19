# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic priority assignment.

The model decides ORDER (which row matters more) because that needs judgment.
This module decides TIER (who gets high / medium / low) because that is
arithmetic, and arithmetic in a prompt is advisory rather than enforced.

Rules mirror the production system this recipe is adapted from:

  * hard caps: at most 10 rows at `high`, at most 10 at `medium`
  * `high` is intent-gated: a row reaches it only if the user has signalled
    that this is something they chose to work on. External urgency alone
    (a deadline, an important sender, a broadcast mention) is not enough.
  * un-gated rows that ranked inside the top 10 cascade down and re-enter
    the medium competition rather than being dropped
  * everything past the two caps is `low`

Rationale for the gate, worth keeping in view while reading the code: the top
tier must be "what the user has chosen to work on", not "what the world has
chosen to escalate at the user".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, List

# Where a user-pinned row sorts relative to the rest. A pin is an instruction,
# so it outranks anything the memory inferred.
_MANUAL_WEIGHT = {"high": 0, "medium": 1, "low": 2, None: 1}

HIGH_CAP = 10
MEDIUM_CAP = 10


@dataclass(frozen=True)
class RankedRow:
    """One surviving row, in the order the model ranked it."""

    source_id: str
    intent_gated: bool
    priority: str | None = None   # filled in by assign_priorities
    global_rank: int | None = None


def assign_priorities(ranked: Iterable[RankedRow]) -> List[RankedRow]:
    """Assign tiers under the hard caps.

    `ranked` must already be in the model's rank order, most important first,
    and must exclude rows that were completed or skipped this pass — those keep
    their previous tier so the audit trail stays readable.
    """
    rows = list(ranked)

    # 1. The high tier is drawn ONLY from gate-passing rows, in rank order.
    #    If fewer than HIGH_CAP pass, the tier is simply smaller. Never pad.
    high_ids = [r.source_id for r in rows if r.intent_gated][:HIGH_CAP]
    high = set(high_ids)

    # 2. Everything else keeps its relative order and competes for medium.
    #    This is where un-gated top-10 rows land: they cascade rather than drop.
    remainder = [r for r in rows if r.source_id not in high]
    medium = {r.source_id for r in remainder[:MEDIUM_CAP]}

    out: List[RankedRow] = []
    for position, row in enumerate(rows, start=1):
        if row.source_id in high:
            tier = "high"
        elif row.source_id in medium:
            tier = "medium"
        else:
            tier = "low"
        out.append(replace(row, priority=tier, global_rank=position))
    return out


def rank_population(rows: Iterable[dict]) -> List[dict]:
    """Order every open obligation, then apply the caps across all of them.

    The caps bound the whole open list, not whichever batch happened to be
    judged last. Ranking only within an envelope lets two twenty-row batches
    leave twenty rows at the top tier and two rows claiming every position,
    which is what this function exists to prevent.

    A row the user pinned is set aside before the caps are computed. Its tier
    is the one the user gave it, so letting it compete would both override the
    instruction and spend a capped slot on a row that is leaving the tier
    anyway.
    """
    ordered = sorted(rows, key=lambda r: (
        _MANUAL_WEIGHT.get(r.get("manual_priority"), 1),
        0 if r.get("intent_gated") else 1,
        r.get("batch_rank") if r.get("batch_rank") is not None else 1_000_000,
        r.get("source_id") or "",
    ))
    unpinned = [r for r in ordered if not r.get("manual_priority")]
    tiers = {a.source_id: a.priority for a in assign_priorities(
        RankedRow(source_id=r["source_id"], intent_gated=bool(r.get("intent_gated")))
        for r in unpinned)}
    return [{**r, "priority": r.get("manual_priority") or tiers[r["source_id"]],
             "global_rank": position}
            for position, r in enumerate(ordered, start=1)]
