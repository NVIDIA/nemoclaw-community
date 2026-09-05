# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ledger adapter, exercised without a network.

Its ingest phase is pure SQLite over the recipe's own schema, so the part that
proves the benchmark can drive a NemoClaw Community memory store is testable
offline. The answer phase is exercised too, against a loopback stub that
returns a canned completion: only a real model call is out of scope. The first
version of this file tested ingest alone, and the untested half was the broken
half -- the answer phase shared one sqlite connection across a thread pool and
raised on the first question of every run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
RUN_PY = REPO / "adapters" / "ledger_rag" / "run.py"
SCHEMA = (REPO.parents[1] / "recipes" / "nvidia" / "memory-driven-chief-of-staff"
          / "profile" / "scripts" / "schema.sql")


def _module():
    spec = importlib.util.spec_from_file_location("ledger_rag_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_recipe_ships_the_schema_this_adapter_scores():
    """If the recipe moves its schema, this adapter must fail loudly, not quietly."""
    assert SCHEMA.exists(), (
        f"the ledger schema is no longer at {SCHEMA}; update DEFAULT_SCHEMA in "
        "adapters/ledger_rag/run.py and this test together"
    )
    assert "CREATE TABLE IF NOT EXISTS items" in SCHEMA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def loaded(tmp_path_factory) -> Path:
    state = tmp_path_factory.mktemp("ledger")
    for part in ("part_a", "part_b"):
        completed = subprocess.run(
            [sys.executable, str(RUN_PY), "ingest",
             "--corpus", str(SELFTEST / "corpus" / part), "--state", str(state)],
            capture_output=True, text=True, timeout=120)
        assert completed.returncode == 0, completed.stderr[-1500:]
    return state


def test_ingest_loads_the_corpus_into_the_recipes_own_tables(loaded):
    conn = sqlite3.connect(loaded / "ledger.db")
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert count == 6, "the selftest corpus is six documents"
    # Written through the recipe's schema, so its constraints applied.
    states = {r[0] for r in conn.execute("SELECT DISTINCT state FROM items")}
    assert states == {"pending"}
    addressing = {r[0] for r in conn.execute("SELECT DISTINCT addressing FROM items")}
    assert addressing <= {"direct", "mentioned", "broadcast"}
    assert conn.execute("SELECT COUNT(*) FROM items WHERE body IS NULL OR body=''").fetchone()[0] == 0


def test_ingest_is_idempotent(loaded, tmp_path):
    """A second ingest of the same half must not double the ledger."""
    conn = sqlite3.connect(loaded / "ledger.db")
    before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    subprocess.run(
        [sys.executable, str(RUN_PY), "ingest",
         "--corpus", str(SELFTEST / "corpus" / "part_a"), "--state", str(loaded)],
        capture_output=True, text=True, timeout=120, check=True)
    conn = sqlite3.connect(loaded / "ledger.db")
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == before


def test_selection_finds_the_document_the_answer_key_cites(loaded):
    module = _module()
    conn = sqlite3.connect(loaded / "ledger.db")
    conn.row_factory = sqlite3.Row
    gold = {json.loads(line)["id"]: json.loads(line)
            for line in (SELFTEST / "gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    questions = [json.loads(line) for line in
                 (SELFTEST / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    checked = hits = 0
    for question in questions:
        want = set(gold[question["id"]].get("gold_source_ids") or [])
        if not want:
            continue
        checked += 1
        if want & {r["source_id"] for r in module._select(conn, question["question"])}:
            hits += 1
    assert checked >= 4
    assert hits == checked, f"selection surfaced the cited document for only {hits}/{checked}"


def test_ingest_never_reads_the_questions_or_the_answer_key(loaded):
    """The phase boundary the maintainer asked for, checked at the source."""
    source = RUN_PY.read_text(encoding="utf-8")
    for forbidden in ("questions.jsonl", "answers.jsonl", "gold"):
        assert forbidden not in source, (
            f"the ledger adapter references {forbidden!r}; ingest and answer must "
            "not be able to reach the question set or the answer key"
        )


def test_the_adapter_declares_its_optional_endpoint(loaded):
    spec = json.loads((REPO / "adapters" / "ledger_rag" / "adapter.json").read_text(encoding="utf-8"))
    assert "ingest needs no network" in spec["requires"]["endpoint"]
    assert "not to the recipe" in spec["description"], (
        "the adapter must say whose behaviour a score describes"
    )


class _StubCompletions(BaseHTTPRequestHandler):
    """Answers any /chat/completions with a fixed, contract-shaped reply."""

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.dumps({
            "choices": [{"message": {"content": json.dumps(
                {"answer": "60%", "source_ids": ["E:2027-02-02T09-00-00__bbbb0001"]})}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # keep the test output readable
        return


@pytest.fixture(scope="module")
def stub_endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubCompletions)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("workers", [1, 3, 6])
def test_the_answer_phase_runs_at_every_worker_count(loaded, stub_endpoint, workers):
    """The defect this catches raised on the first question at every count.

    ThreadPoolExecutor never runs work on the calling thread, so no worker
    count avoided a connection opened outside the pool.
    """
    questions = (SELFTEST / "questions.jsonl").read_text(encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(RUN_PY), "answer", "--state", str(loaded),
         "--workers", str(workers)],
        input=questions, capture_output=True, text=True, timeout=120,
        env={**os.environ, "OPENAI_BASE_URL": stub_endpoint,
             "OPENAI_API_KEY": "stub", "MNEMO_MODEL": "stub-model"},
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert len(rows) == 6, f"answered {len(rows)} of 6 questions"
    assert all(r["answer"] for r in rows), "an answer came back empty"
    assert all(r["source_ids"] for r in rows), "no evidence was attributed"
