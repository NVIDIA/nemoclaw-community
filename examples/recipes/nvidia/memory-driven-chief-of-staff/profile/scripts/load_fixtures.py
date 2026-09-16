# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay the fixtures through the real ingest path.

This deliberately reuses `normalize` and `_db` rather than inserting rows
directly. A walkthrough that takes a shortcut around the code it is
demonstrating proves nothing, and normalization is the layer most likely to be wrong.

Also copies the seed memory into the profile workspace. A live judging turn
reads those pages before it decides whether the user chose a given piece of
work; the fixture path has that decision recorded already, so the pages are
here for the live path and for the memory self-check rather than to change what
the walkthrough prints.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from _db import ensure_store, ledger_path, write_txn
from normalize import graph_message_to_item, insert_items, slack_message_to_item

USER_ADDRESS = "avery.chen@example.com"
USER_SLACK_ID = "U0AVERY001"


def load(fixtures: Path) -> dict[str, int]:
    ensure_store()

    graph = json.loads((fixtures / "graph_messages.json").read_text(encoding="utf-8"))
    slack = json.loads((fixtures / "slack_messages.json").read_text(encoding="utf-8"))

    items = [graph_message_to_item(m, USER_ADDRESS) for m in graph["value"]]
    for channel in slack["channels"]:
        for msg in slack["history"][channel["id"]]["messages"]:
            items.append(slack_message_to_item(msg, channel, USER_SLACK_ID))

    with write_txn() as conn:
        added = insert_items(conn, items)
        conn.execute(
            "INSERT INTO cursors(source, scope, cursor) VALUES ('email','inbox',?)"
            " ON CONFLICT(source, scope) DO UPDATE SET cursor=excluded.cursor",
            (graph["@odata.deltaLink"],))

    memory_src = fixtures / "memory"
    memory_dst = ledger_path().parent.parent / "memory"
    from memory_pages import writer
    from memory_io import MemoryConflict
    import memory_journal as journal
    import uuid
    with writer(check_skills=False):
        if memory_src.is_dir() and not memory_dst.exists():
            with journal.connection() as conn:
                if conn.execute("SELECT 1 FROM pages LIMIT 1").fetchone():
                    raise MemoryConflict("fixture seeding requires a fresh memory registry")
                instance = journal.store_id(conn)
            today = datetime.now(timezone.utc).date().isoformat()
            files = []
            for source in sorted(memory_src.rglob("*.md")):
                if source.name.startswith("._"):
                    continue
                text = re.sub(r"^updated: \d{4}-\d{2}-\d{2}$", f"updated: {today}",
                              source.read_text(encoding="utf-8"), count=1, flags=re.M)
                files.append((str(source.relative_to(memory_src)), None, text.encode()))
            files.sort(key=lambda item: item[0] == "index.md")
            if files:
                operation_id = str(uuid.uuid4())
                journal.prepare(operation_id=operation_id, request_id=operation_id,
                                request_digest=journal.json_digest([name for name, _, _ in files]),
                                instance=instance, op_type="legacy_write", actor="maintenance", files=files, effects={})
                journal.recover_locked()

    return {"seen": len(items), "added": added, "memory": str(memory_dst),
            "seeded": memory_dst.is_dir()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", type=Path, required=True)
    print(json.dumps(load(ap.parse_args().fixtures), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
