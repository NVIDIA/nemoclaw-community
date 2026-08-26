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

A file that cannot be read stops collection. An earlier version treated an
unreadable file as no rules at all, on the reasoning that a typo should not
halt the intake — but the guarantee this module exists to provide is that
excluded content is never written, and failing open converts a typo into a
silent breach of exactly that. The user finds out when the thing they
excluded is already on disk. Stopping is loud, recoverable, and honest about
which of the two failures happened.
"""

from __future__ import annotations

import json
from typing import Any

RULES_FILE = "exclusions.json"


def rules_path():
    from _db import ledger_path
    return ledger_path().parent.parent / RULES_FILE


class ExclusionsUnreadable(Exception):
    """The rules exist but cannot be honoured, so nothing may be written."""


def load_rules() -> dict[str, set[str]]:
    """Read the rules, or refuse to proceed without them.

    Absent is not the same as broken. No file means no rules, which is the
    ordinary state of a fresh install and must stay free. A file that is
    present but malformed is a different thing: the user wrote it in order to
    keep something out, and continuing without it writes exactly what they
    were trying to prevent.
    """
    empty: dict[str, set[str]] = {"senders": set(), "domains": set(),
                                  "channels": set()}
    path = rules_path()
    if not path.exists():
        return empty
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExclusionsUnreadable(
            f"{path} exists but could not be read ({exc.strerror or exc}). "
            "Nothing has been stored. Fix the file or remove it.") from exc
    try:
        declared = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExclusionsUnreadable(
            f"{path} is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}: {exc.msg}). Nothing has been stored, because the "
            "rules that say what to keep out cannot be read.") from exc
    if not isinstance(declared, dict):
        raise ExclusionsUnreadable(
            f"{path} must hold a JSON object with `senders`, `domains` and "
            f"`channels` keys; found {type(declared).__name__}. Nothing has "
            "been stored.")
    # An unknown key is a typo, and a typo here is the failure this whole
    # module is trying to prevent: `{"sender": [...]}` parsed cleanly, matched
    # nothing, and let through exactly what the user wrote it to keep out.
    # Silence is the worst possible response to it.
    unknown = sorted(set(declared) - set(empty))
    if unknown:
        raise ExclusionsUnreadable(
            f"{path}: unknown key(s) {', '.join(unknown)}. Expected "
            f"{', '.join(sorted(empty))}. Nothing has been stored — a "
            "misspelled key would silently exclude nothing.")

    for key in empty:
        value = declared.get(key, [])
        if not isinstance(value, (list, tuple)):
            raise ExclusionsUnreadable(
                f"{path}: `{key}` must be a list of strings, not "
                f"{type(value).__name__}. Nothing has been stored.")
        # `str()` on a non-string used to make `123` into the rule `"123"`,
        # which matches nothing and reads as a working rule. A number here is
        # a mistake, not a value to coerce.
        for member in value:
            if not isinstance(member, str):
                raise ExclusionsUnreadable(
                    f"{path}: `{key}` contains {member!r} "
                    f"({type(member).__name__}); every entry must be a "
                    "string. Nothing has been stored.")

    return {
        key: {v.strip().lower() for v in declared.get(key, []) if v.strip()}
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
    # `sender_id` and `sender_address` are set by the normalizers and dropped
    # before the insert. They exist because `sender` holds a display name
    # whenever the source supplies one — a Slack user the person can rename,
    # a mail sender whose address never appears in the row. Matching only on
    # `sender` meant a domain rule matched nothing at all on real mail, and a
    # `U…` rule matched nothing on real Slack. Both were documented as
    # working.
    sender_id = str(item.get("sender_id") or "").strip().lower()
    if sender_id and sender_id in rules["senders"]:
        return True

    address = str(item.get("sender_address") or "").strip().lower()
    if address and address in rules["senders"]:
        return True

    for candidate in (address, sender):
        if candidate and "@" in candidate:
            domain = candidate.rsplit("@", 1)[-1]
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
