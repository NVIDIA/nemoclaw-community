# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keep chosen senders, domains and channels out of the store entirely.

Not hidden at display: never written. A rule that filters what is shown leaves
the text on disk, which is no use to somebody excluding their doctor, a
recruiter, or a channel where colleagues discuss their own pay. The only
exclusion worth the name happens before the row exists.

That is why this is applied in `insert_items` rather than in a collector. Every
writer goes through that one function — the fixture loader today, the Slack
collector when it lands, whatever arrives after — so the property holds for all
of them without any of them having to remember it, and a new writer cannot
quietly opt out.

Rules live in `workspace/exclusions.json`:

    {
      "senders":  ["recruiter@agency.example", "U01RECRUIT"],
      "domains":  ["agency.example"],
      "channels": ["C0SALARY01", "D0PRIVATE1"]
    }

A sender matches on the value stored in `sender`, which is a display name or an
address depending on the source, and on the raw id when the collector knows it.
A domain matches the part after `@`. A channel matches `scope`, which is the
mail folder or the Slack channel id.

Matching is case-insensitive and exact — no globs. A pattern language here
would be a way to exclude more than intended by accident, and the failure is
silent: nothing arrives, and nothing says why.
"""

from __future__ import annotations

import json
from typing import Any

RULES_FILE = "exclusions.json"


def rules_path():
    from _db import ledger_path
    return ledger_path().parent.parent / RULES_FILE


def load_rules() -> dict[str, set[str]]:
    """Read the rules, or none at all.

    An unreadable file yields no rules rather than an error. That is the
    deliberate direction: a typo in this file must not stop the intake, and the
    consequence — a message arriving that the user meant to exclude — is
    visible to them, where a stalled pipeline would not be.
    """
    empty: dict[str, set[str]] = {"senders": set(), "domains": set(),
                                  "channels": set()}
    path = rules_path()
    if not path.exists():
        return empty
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(declared, dict):
        return empty
    return {
        key: {str(v).strip().lower() for v in declared.get(key, [])
              if str(v).strip()}
        for key in empty
    }


def excluded(item: dict[str, Any], rules: dict[str, set[str]]) -> bool:
    """Does this row match a rule?"""
    if not any(rules.values()):
        return False

    scope = str(item.get("scope") or "").strip().lower()
    if scope and scope in rules["channels"]:
        return True

    sender = str(item.get("sender") or "").strip().lower()
    if sender and sender in rules["senders"]:
        return True

    # `sender_id` is set by a collector that knows the source's own identifier,
    # so a Slack user can be excluded by `U…` rather than by a display name
    # they can change.
    sender_id = str(item.get("sender_id") or "").strip().lower()
    if sender_id and sender_id in rules["senders"]:
        return True

    if sender and "@" in sender:
        domain = sender.rsplit("@", 1)[-1]
        if domain in rules["domains"]:
            return True

    return False


def partition(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Split the batch into what may be stored and a count of what may not."""
    rules = load_rules()
    if not any(rules.values()):
        return items, 0
    keep = [item for item in items if not excluded(item, rules)]
    return keep, len(items) - len(keep)
