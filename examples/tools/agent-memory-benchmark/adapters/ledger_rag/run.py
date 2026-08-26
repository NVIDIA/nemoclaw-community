#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Score the Memory-Driven Chief of Staff ledger as a retrieval store.

**What this measures, and what it does not.** The ledger is a NemoClaw
Community memory store that lives in this repository, and this adapter
demonstrates that the benchmark can drive one end to end: it loads the corpus
into the ledger using the recipe's own `schema.sql`, then answers by selecting
candidates out of it and passing them to a model.

What that scores is *candidate selection over the ledger, plus the model*. It
is not a score of the recipe's own behaviour. The recipe's ledger is built for
triage and ranking -- `items` holds subjects, senders and bodies, and its own
scripts record judgments over them -- and it has no question-answering path.
The selection and the answer call in this file belong to the adapter, not to
the recipe, and nothing here writes to or changes the recipe.

Read a number produced by this adapter as "the harness can exercise that
store", never as "the recipe scores X".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters._lib import vectorstore as vs  # noqa: E402
from bench.answer_contract import ANSWER_CONTRACT  # noqa: E402

# The recipe ships the schema; this adapter does not copy it, so the store
# under test is the real one and stays the real one as the recipe evolves.
# .../examples/tools/agent-memory-benchmark/adapters/ledger_rag/run.py
#   parents[4] is examples/
DEFAULT_SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "recipes" / "nvidia" / "memory-driven-chief-of-staff"
    / "profile" / "scripts" / "schema.sql"
)
TOP_K = int(os.environ.get("MNEMO_LEDGER_TOP_K", "12"))
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "what", "which", "who", "whom", "when", "where", "how",
    "did", "does", "do", "has", "have", "had", "it", "its", "this", "that",
    "as", "at", "by", "be", "been", "with", "from", "any", "all",
}


def _schema_path() -> Path:
    override = os.environ.get("MNEMO_LEDGER_SCHEMA")
    path = Path(override).expanduser() if override else DEFAULT_SCHEMA
    if not path.exists():
        raise SystemExit(
            f"the ledger schema is not at {path}. This adapter scores the "
            "Memory-Driven Chief of Staff store, so it needs that example "
            "present, or MNEMO_LEDGER_SCHEMA pointing at its schema.sql."
        )
    return path


def _frontmatter(text: str) -> tuple[dict, str]:
    """Split a corpus document into its frontmatter and its body.

    Deliberately not a YAML parser: the corpus frontmatter is flat scalars plus
    two list fields this adapter does not read, and depending on PyYAML would
    put a third-party package between the benchmark and a shipped baseline.
    """
    if not text.startswith("---"):
        return {}, text
    _, _, rest = text.partition("---\n")
    head, _, body = rest.partition("\n---")
    meta: dict = {}
    for line in head.splitlines():
        if line.startswith((" ", "-")) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta, body.lstrip("\n")


def cmd_ingest(corpus: Path, state: Path) -> None:
    """Load one corpus half into the ledger. No model call, no network."""
    state.mkdir(parents=True, exist_ok=True)
    db = state / "ledger.db"
    conn = sqlite3.connect(db)
    conn.executescript(_schema_path().read_text(encoding="utf-8"))
    rows = []
    for path in sorted(corpus.rglob("*.md")):
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
        doc_id = meta.get("doc_id")
        if not doc_id:
            continue
        source = "email" if meta.get("source") == "email" else "slack"
        event_at = meta.get("date", "")
        if len(event_at) == 10:  # a channel-day carries a date, not a timestamp
            event_at = f"{event_at}T00:00:00Z"
        rows.append((
            doc_id, source,
            meta.get("folder") or meta.get("channel_name") or "unknown",
            meta.get("conversation_id"), event_at,
            meta.get("from") or meta.get("channel_name"),
            meta.get("subject"), body, None,
            "direct" if source == "email" else "broadcast",
            1 if str(meta.get("unread", "")).lower() == "true" else 0,
            "pending",
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO items (source_id, source, scope, thread_ref, event_at,"
        " sender, subject, body, permalink, addressing, unread, state)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    print(f"[ledger_rag] loaded {len(rows)} documents into {db}", file=sys.stderr)


def _terms(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9._-]{2,}", question.lower())
    return [w for w in words if w not in STOPWORDS]


def _select(conn: sqlite3.Connection, question: str) -> list[sqlite3.Row]:
    """Rank ledger rows by how many question terms they contain.

    Plain SQL over the recipe's own columns, on purpose: an embedding index
    would be measuring the index, not the store.
    """
    terms = _terms(question)
    if not terms:
        return []
    score = " + ".join(
        "(CASE WHEN lower(COALESCE(subject,'') || ' ' || COALESCE(body,'')) LIKE ? THEN 1 ELSE 0 END)"
        for _ in terms)
    sql = (f"SELECT source_id, event_at, sender, subject, body, ({score}) AS hits"
           " FROM items WHERE hits > 0 ORDER BY hits DESC, event_at DESC LIMIT ?")
    return conn.execute(sql, [f"%{t}%" for t in terms] + [TOP_K]).fetchall()


def cmd_answer(state: Path, workers: int) -> None:
    # One connection per worker thread. A sqlite3 connection is bound to the
    # thread that opened it, and sharing one across the pool with
    # check_same_thread=False trades the error for a race on the schema cache.
    local = threading.local()

    def conn() -> sqlite3.Connection:
        if not hasattr(local, "db"):
            local.db = sqlite3.connect(state / "ledger.db")
            local.db.row_factory = sqlite3.Row
        return local.db

    questions = [json.loads(line) for line in sys.stdin.read().splitlines() if line.strip()]
    model = os.environ.get("MNEMO_MODEL") or "gpt-4o"

    def answer_one(question: dict) -> dict:
        rows = _select(conn(), question["question"])
        context = "\n\n".join(
            f"[{r['source_id']}] {r['event_at']} {r['sender'] or ''}\n"
            f"{r['subject'] or ''}\n{(r['body'] or '')[:1800]}" for r in rows)
        body = vs.post(
            "/chat/completions",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": ANSWER_CONTRACT},
                    {"role": "user",
                     "content": f"LEDGER CANDIDATES:\n{context}\n\nQUESTION: {question['question']}"},
                ],
                "max_tokens": 3000,
            },
        )
        parsed = vs.parse_json_object(body["choices"][0]["message"].get("content") or "")
        return {"id": question["id"], "answer": parsed.get("answer", ""),
                "source_ids": parsed.get("source_ids") or [r["source_id"] for r in rows[:3]]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(answer_one, questions):
            print(json.dumps(row), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--corpus", required=True, type=Path)
    ingest.add_argument("--state", required=True, type=Path)
    answer = sub.add_parser("answer")
    answer.add_argument("--state", required=True, type=Path)
    answer.add_argument("--workers", type=int, default=int(os.environ.get("MNEMO_RAG_WORKERS", "6")))
    args = parser.parse_args()
    if args.command == "ingest":
        cmd_ingest(args.corpus.resolve(), args.state.resolve())
    else:
        cmd_answer(args.state.resolve(), args.workers)


if __name__ == "__main__":
    main()
