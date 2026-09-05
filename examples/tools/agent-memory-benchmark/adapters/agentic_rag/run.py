#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Agentic retrieval baseline: the model writes its own queries, over rounds.

Same index as `naive_rag`, different search strategy. Instead of one fixed top-k
lookup against the question text, the model decides what to search for, reads
what comes back, and decides whether it has enough — up to a round limit. That
is the honest middle row of the comparison: a system that digests nothing at
ingest but is allowed to work at query time.

Rounds are capped rather than left to the model, so the cost axis stays
comparable: an agent permitted to search forever would win accuracy by spending
without bound, which is the trade this benchmark exists to make visible.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters._lib import vectorstore as vs  # noqa: E402
from bench.answer_contract import ANSWER_CONTRACT  # noqa: E402

MAX_ROUNDS = 3
QUERIES_PER_ROUND = 3
TOP_K_PER_QUERY = 5

PLANNER_PROMPT = """You are searching a corpus of one person's email and chat to answer a question.

You cannot see the corpus directly. You write search queries; each returns the
passages most similar to it. Write queries that would appear near the answer —
names, dates, project names, exact phrases — not restatements of the question.

Return STRICT JSON, no prose:
{"queries": ["...", "..."], "reasoning": "one short line"}

If the passages you have already seen fully answer the question, return:
{"done": true}
"""


def _plan(question: str, seen: list[dict], model: str, rounds_left: int) -> dict:
    context = "\n\n".join(f"=== {c['doc_id']} ===\n{c['text'][:1200]}" for c in seen[-12:])
    user = (
        f"QUESTION: {question}\n\n"
        f"PASSAGES RETRIEVED SO FAR ({len(seen)}):\n{context or '(nothing yet)'}\n\n"
        f"You may run {rounds_left} more round(s), up to {QUERIES_PER_ROUND} queries each."
    )
    body = vs.post(
        "/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": user},
            ],
            "max_tokens": 2000,
        },
    )
    return vs.parse_json_object(body["choices"][0]["message"].get("content") or "")


def _answer(question: str, seen: list[dict], model: str) -> dict:
    context = "\n\n".join(f"=== {c['doc_id']} ===\n{c['text']}" for c in seen)
    body = vs.post(
        "/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": ANSWER_CONTRACT},
                {"role": "user", "content": f"RETRIEVED CONTEXT:\n{context}\n\nQUESTION: {question}"},
            ],
            "max_tokens": 3000,
        },
    )
    content = body["choices"][0]["message"].get("content") or ""
    parsed = vs.parse_json_object(content)
    return {
        "answer": parsed.get("answer", content.strip()),
        "source_ids": parsed.get("source_ids", [c["doc_id"] for c in seen[:3]]),
    }


def cmd_ingest(corpus: Path, state: Path) -> None:
    added = vs.build_index(corpus, state)
    print(f"[agentic_rag] indexed {added} chunks from {corpus.name}", file=sys.stderr)


def cmd_answer(state: Path, workers: int) -> None:
    chunks = vs.load_store(state)
    questions = [json.loads(line) for line in sys.stdin.read().splitlines() if line.strip()]
    model = os.environ.get("MNEMO_MODEL") or "gpt-4o"

    def answer_one(question: dict) -> dict:
        seen: list[dict] = []
        seen_keys: set[tuple[str, int]] = set()
        for round_index in range(MAX_ROUNDS):
            plan = _plan(question["question"], seen, model, MAX_ROUNDS - round_index)
            if plan.get("done") and seen:
                break
            queries = [q for q in plan.get("queries", []) if isinstance(q, str) and q.strip()]
            if not queries:
                queries = [question["question"]]
            for vector in vs.embed(queries[:QUERIES_PER_ROUND]):
                for hit in vs.search(chunks, vector, TOP_K_PER_QUERY):
                    key = (hit["doc_id"], hash(hit["text"]))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        seen.append(hit)
        row = _answer(question["question"], seen, model)
        row["id"] = question["id"]
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(answer_one, questions):
            print(json.dumps(row, ensure_ascii=False), flush=True)


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
        cmd_ingest(args.corpus, args.state)
    else:
        cmd_answer(args.state, args.workers)


if __name__ == "__main__":
    main()
