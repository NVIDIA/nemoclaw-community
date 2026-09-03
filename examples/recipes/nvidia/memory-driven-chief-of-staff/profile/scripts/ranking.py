# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic priority assignment.

The model decides ORDER (which row matters more) because that needs judgment.
This module decides TIER (who gets high / medium / low) because that is
arithmetic, and arithmetic in a prompt is advisory rather than enforced.

The rules this module enforces:

  * hard caps: at most 10 rows at `high`, at most 10 at `medium`
  * `high` is intent-gated: a row reaches it only if the user has signalled
    that this is something they chose to work on. External urgency alone
    (a deadline, an important sender, a broadcast mention) is not enough.
  * un-gated rows that ranked inside the top 10 cascade down and re-enter
    the medium competition rather than being dropped
  * a user pin outranks the gate but is still counted against the caps: it
    decides the order in which rows claim a tier, not whether the tier has a
    size, so an eleventh row pinned `high` cascades like any other overflow
  * everything past the two caps is `low`

Rationale for the gate, worth keeping in view while reading the code: the top
tier must be "what the user has chosen to work on", not "what the world has
chosen to escalate at the user".
"""

from __future__ import annotations

from typing import Iterable, List

# Where a user-pinned row sorts relative to the rest. A pin is an instruction,
# so it outranks anything the memory inferred.
_MANUAL_WEIGHT = {"high": 0, "medium": 1, "low": 2, None: 1}

HIGH_CAP = 10
MEDIUM_CAP = 10


def _desired(row: dict) -> str | None:
    """The tier a row is asking for, before the caps are applied.

    A pin is the user's answer and outranks the gate. An un-pinned row that
    passes the gate asks for the top tier; anything else asks for nothing and
    competes for the middle by position.
    """
    manual = row.get("manual_priority")
    if manual:
        return manual
    return "high" if row.get("intent_gated") else None


def rank_population(rows: Iterable[dict]) -> List[dict]:
    """Order every open obligation, then apply the caps across all of them.

    The caps bound the whole open list, not whichever batch happened to be
    judged last. Ranking only within an envelope lets two twenty-row batches
    leave twenty rows at the top tier and two rows claiming every position,
    which is what this function exists to prevent.

    Pinned rows are ranked first but are still counted against the caps. They
    have to be: "the ranked list is short by construction" is the property this
    recipe sells, and a tier that any number of pins can grow is short only by
    instruction. Eleven rows pinned high therefore produce ten high rows and
    one that cascades — the pin decides the order in which rows claim the tier,
    not whether the tier has a size.
    """
    ordered = sorted(rows, key=lambda r: (
        _MANUAL_WEIGHT.get(r.get("manual_priority"), 1),
        0 if r.get("intent_gated") else 1,
        r.get("batch_rank") if r.get("batch_rank") is not None else 1_000_000,
        r.get("source_id") or "",
    ))

    # Tiers are tracked by position rather than by source_id. The store makes
    # source_id unique, but keying a cap on a value the caller supplies means a
    # repeated one quietly admits two rows into a ten-row tier, and a cap that
    # can be widened by malformed input is not much of a cap.
    high = set([i for i, r in enumerate(ordered) if _desired(r) == "high"][:HIGH_CAP])

    # Everything else competes for the middle tier by position, except rows the
    # user pinned to the bottom: a pin down is an instruction too, and it would
    # be a strange reading of it to hand the row a better tier than it had.
    remainder = [i for i, r in enumerate(ordered)
                 if i not in high and _desired(r) != "low"]
    medium = set(remainder[:MEDIUM_CAP])

    out: List[dict] = []
    for index, row in enumerate(ordered):
        if index in high:
            tier = "high"
        elif index in medium:
            tier = "medium"
        else:
            tier = "low"
        out.append({**row, "priority": tier, "global_rank": index + 1})
    return out
