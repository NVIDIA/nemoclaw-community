# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A chunk-and-embed index, shared by the retrieval adapters.

Both retrieval baselines build the *same* index from the same corpus. Keeping
that in one place is what makes their comparison mean something: the only
difference between `naive_rag` and `agentic_rag` is the search policy on top —
one fixed top-k lookup versus an agent writing its own queries over several
rounds.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from pathlib import Path

CHUNK_CHARS = 3200
CHUNK_OVERLAP = 400
EMBED_MODEL = os.environ.get("MNEMO_EMBED_MODEL", "azure/openai/text-embedding-3-small")


def base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MNEMO_API_KEY")
    if key:
        return key
    raise SystemExit("no API key available (set OPENAI_API_KEY)")


def post(path: str, payload: dict, timeout: int = 300) -> dict:
    request = urllib.request.Request(
        f"{base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
    )
    last: Exception | None = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except Exception as exc:  # shared endpoints rate-limit; retry a few times
            last = exc
    raise SystemExit(f"request to {path} failed: {last}")


def embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for start in range(0, len(texts), 64):
        body = post("/embeddings", {"model": EMBED_MODEL, "input": texts[start : start + 64]})
        out += [row["embedding"] for row in body["data"]]
    return out


def chunk(text: str) -> list[str]:
    pieces: list[str] = []
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for start in range(0, max(len(text), 1), step):
        piece = text[start : start + CHUNK_CHARS].strip()
        if piece:
            pieces.append(piece)
        if start + CHUNK_CHARS >= len(text):
            break
    return pieces


def doc_id_of(text: str) -> str:
    for line in text.splitlines()[:6]:
        if line.startswith("doc_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def build_index(corpus: Path, state: Path) -> int:
    """Index every document under ``corpus`` not already in the store."""
    state.mkdir(parents=True, exist_ok=True)
    store_path = state / "store.json"
    store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {"chunks": []}
    known = {c["doc_id"] for c in store["chunks"]}

    pending: list[dict] = []
    for path in sorted(corpus.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_id = doc_id_of(text)
        if not doc_id or doc_id in known:
            continue
        pending += [{"doc_id": doc_id, "text": piece} for piece in chunk(text)]

    if pending:
        for item, vector in zip(pending, embed([p["text"] for p in pending])):
            item["vector"] = vector
        store["chunks"] += pending
    store_path.write_text(json.dumps(store), encoding="utf-8")
    return len(pending)


def load_store(state: Path) -> list[dict]:
    return json.loads((state / "store.json").read_text(encoding="utf-8"))["chunks"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(chunks: list[dict], vector: list[float], k: int) -> list[dict]:
    return sorted(chunks, key=lambda c: cosine(vector, c["vector"]), reverse=True)[:k]


def parse_json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
