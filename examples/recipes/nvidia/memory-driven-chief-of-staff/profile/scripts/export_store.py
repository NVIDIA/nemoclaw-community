# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Write out everything this recipe holds, in a form a person can read.

Somebody who wants to know what an assistant has kept about them should not
have to open a database to find out, and somebody leaving should be able to
take it with them. So this writes the whole store and the whole memory as
Markdown and JSON side by side: the Markdown to be read, the JSON to be
processed.

`store.json` is the complete record: every column of every row, nothing
summarised and nothing dropped. `store.md` is the same content laid out to be
read, and it is explicit about the one thing it does differently — a long body
is shown to a bounded length with the remainder marked, because a Markdown
file with a hundred-kilobyte message in it stops being readable, which was the
only reason to write it. When the two disagree, the JSON is the answer.

An export that quietly left something out would be worse than none, because it
would answer the question wrongly. So a table that cannot be read is a failed
export rather than an empty section, and both files are written with the same
owner-only permissions as the store they came from.

    python3 export_store.py                 # to ./export-<date>/
    python3 export_store.py --to <dir>

Pairs with `reset.py`, which removes what this shows. The two are documented
together because somebody withdrawing consent usually wants both: see what is
held, then have it gone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

from _db import ensure_store, ledger_path

TABLES = ("items", "obligations", "events", "cursors", "meta")


# How much of a body `store.md` shows before marking the remainder. The JSON
# holds all of it; this bound exists so the readable form stays readable.
BODY_PREVIEW = 2000


def _write_private(path: Path, text: str) -> None:
    """Write owner-only, and be owner-only from the first byte.

    Creating the file and then chmod-ing it leaves a window in which the
    content is world-readable, which on a shared machine is the whole risk.
    """
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def _narrow(root: Path) -> None:
    """Owner-only, everywhere under the export."""
    os.chmod(root, 0o700)
    for path in root.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def as_markdown(data: dict[str, list[dict]]) -> str:
    """The same content, laid out to be read rather than parsed."""
    out: list[str] = ["# What this assistant is holding", ""]
    out.append(f"Exported {date.today().isoformat()}.")
    out.append("")

    obligations = data.get("obligations", [])
    out.append(f"## Obligations ({len(obligations)})")
    out.append("")
    if not obligations:
        out.append("None.")
    for row in sorted(obligations, key=lambda r: r.get("global_rank") or 0):
        rank = row.get("global_rank")
        out.append(f"- **{row.get('title') or '(untitled)'}**")
        out.append(f"  - rank {rank}, {row.get('priority')}, "
                   f"{row.get('status')}")
        out.append(f"  - from `{row.get('source_id')}`")
    out.append("")

    items = data.get("items", [])
    held = sum(1 for r in items if r.get("body"))
    cleared = sum(1 for r in items if r.get("body_cleared_at"))
    out.append(f"## Messages ({len(items)})")
    out.append("")
    out.append(f"{held} still hold their text. {cleared} have had it cleared "
               "by the retention pass; the rest never carried any.")
    out.append("")
    for row in sorted(items, key=lambda r: r.get("event_at") or ""):
        out.append(f"- `{row.get('event_at')}` **{row.get('sender') or '?'}** "
                   f"— {row.get('subject') or '(no subject)'}")
        if row.get("body"):
            body = " ".join(str(row["body"]).split())
            if len(body) > BODY_PREVIEW:
                out.append(f"  - {body[:BODY_PREVIEW]}")
                out.append(f"  - _(body continues; {len(body) - BODY_PREVIEW} "
                           "more characters in `store.json`)_")
            else:
                out.append(f"  - {body}")
        elif row.get("body_cleared_at"):
            out.append(f"  - text cleared {row['body_cleared_at']}")
    out.append("")

    events = data.get("events", [])
    out.append(f"## What happened, and who did it ({len(events)})")
    out.append("")
    if not events:
        out.append("Nothing yet.")
    for row in sorted(events, key=lambda r: r.get("ts") or ""):
        out.append(f"- `{row.get('ts')}` {row.get('event_type')} "
                   f"by {row.get('actor')} on `{row.get('obligation_id')}`")
    out.append("")
    return "\n".join(out) + "\n"


def export(destination: Path) -> dict[str, object]:
    ensure_store()
    destination.mkdir(parents=True, exist_ok=True)
    # The store is deliberately owner-only. An export that widens that is a
    # copy of the same content readable by every account on the machine, which
    # is a quieter version of not having protected it at all.
    os.chmod(destination, 0o700)

    data: dict[str, list[dict]] = {}
    with sqlite3.connect(ledger_path()) as conn:
        for table in TABLES:
            # An unreadable table used to become an empty one, which produces
            # an export that looks complete and is not — the failure mode this
            # command exists to avoid. Let it raise.
            data[table] = rows(conn, table)

    _write_private(destination / "store.json",
                   json.dumps(data, indent=2, ensure_ascii=False))
    _write_private(destination / "store.md", as_markdown(data))

    memory_src = ledger_path().parent.parent / "memory"
    copied = 0
    if memory_src.is_dir():
        memory_dst = destination / "memory"
        if memory_dst.exists():
            shutil.rmtree(memory_dst)
        shutil.copytree(memory_src, memory_dst,
                        ignore=shutil.ignore_patterns("._*", ".DS_Store"))
        copied = sum(1 for _ in memory_dst.rglob("*.md"))

    policy_src = ledger_path().parent.parent / "policy"
    if policy_src.is_dir():
        shutil.copytree(policy_src, destination / "policy", dirs_exist_ok=True)

    # copytree carries the source's modes, and a wiki page written by an
    # agent turn has ordinary ones. Narrow the whole tree rather than trusting
    # what it arrived with.
    _narrow(destination)

    return {
        "to": str(destination),
        "obligations": len(data.get("obligations", [])),
        "messages": len(data.get("items", [])),
        "events": len(data.get("events", [])),
        "memory_pages": copied,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path,
                        default=Path(f"export-{date.today().isoformat()}"),
                        help="directory to write into")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export(args.to)))
    except OSError as exc:
        print(f"could not write the export: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
