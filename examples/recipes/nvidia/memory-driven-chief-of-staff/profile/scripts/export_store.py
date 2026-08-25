# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Write out everything this recipe holds, in a form a person can read.

Somebody who wants to know what an assistant has kept about them should not
have to open a database to find out, and somebody leaving should be able to
take it with them. So this writes the whole store and the whole memory as
Markdown and JSON side by side: the Markdown to be read, the JSON to be
processed.

Nothing is summarised or omitted. An export that quietly left something out
would be worse than none, because it would answer the question wrongly.

    python3 export_store.py                 # to ./export-<date>/
    python3 export_store.py --to <dir>

Pairs with `reset.py`, which removes what this shows. The two are documented
together because somebody withdrawing consent usually wants both: see what is
held, then have it gone.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

from _db import ensure_store, ledger_path

TABLES = ("items", "obligations", "events", "cursors", "meta")


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
            out.append(f"  - {body[:300]}")
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

    data: dict[str, list[dict]] = {}
    with sqlite3.connect(ledger_path()) as conn:
        for table in TABLES:
            try:
                data[table] = rows(conn, table)
            except sqlite3.Error:
                data[table] = []

    (destination / "store.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (destination / "store.md").write_text(as_markdown(data), encoding="utf-8")

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
