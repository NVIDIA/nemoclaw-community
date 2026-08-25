#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Reference baseline: embed-and-retrieve, no ingest-time reasoning, one lookup.

This adapter anchors the cheap end of the trade-off the benchmark measures. It
spends almost nothing at ingest (embeddings only, no reasoning) and does exactly
one retrieval per question — no query rewriting, no reranking, no second round.
It is deliberately a floor, not a strong RAG: `agentic_rag` shares its index and
adds the search policy, so the difference between their rows is what search
policy buys.
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

TOP_K = 8


def cmd_ingest(corpus: Path, state: Path) -> None:
    added = vs.build_index(corpus, state)
    print(f"[naive_rag] indexed {added} chunks from {corpus.name}", file=sys.stderr)


def cmd_answer(state: Path, workers: int) -> None:
    chunks = vs.load_store(state)
    questions = [json.loads(line) for line in sys.stdin.read().splitlines() if line.strip()]
    model = os.environ.get("MNEMO_MODEL") or "gpt-4o"
    vectors = vs.embed([q["question"] for q in questions])

    def answer_one(pair: tuple[dict, list[float]]) -> dict:
        question, vector = pair
        ranked = vs.search(chunks, vector, TOP_K)
        context = "\n\n".join(f"=== {c['doc_id']} ===\n{c['text']}" for c in ranked)
        body = vs.post(
            "/chat/completions",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": ANSWER_CONTRACT},
                    {"role": "user", "content": f"RETRIEVED CONTEXT:\n{context}\n\nQUESTION: {question['question']}"},
                ],
                "max_tokens": 3000,
            },
        )
        content = body["choices"][0]["message"].get("content") or ""
        parsed = vs.parse_json_object(content)
        return {
            "id": question["id"],
            "answer": parsed.get("answer", content.strip()),
            "source_ids": parsed.get("source_ids", [c["doc_id"] for c in ranked[:3]]),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(answer_one, zip(questions, vectors)):
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
