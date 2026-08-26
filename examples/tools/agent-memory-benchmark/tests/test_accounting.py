# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cost accounting fails closed.

The proxy used to increment its call count only when a response carried usage,
so a run against an endpoint that omits usage produced a valid-looking score
with a cost of zero. A cost nobody measured must not read as a cost of zero,
so the proxy now counts what it forwarded as well as what it could count, and
a run with a gap between the two is marked invalid.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
ADAPTER = REPO / "selftest" / "calling"


@pytest.fixture(scope="module", autouse=True)
def calling_adapter():
    """An adapter that makes exactly one model call per question."""
    ADAPTER.mkdir(parents=True, exist_ok=True)
    (ADAPTER / "run.py").write_text(
        "import json, os, sys, urllib.request\n"
        "if sys.argv[1] == 'ingest':\n    sys.exit(0)\n"
        "base = os.environ['OPENAI_BASE_URL']\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n        continue\n"
        "    q = json.loads(line)\n"
        "    r = urllib.request.Request(f'{base}/chat/completions',\n"
        "        data=json.dumps({'model': 'm', 'messages': []}).encode(),\n"
        "        headers={'Content-Type': 'application/json'})\n"
        "    b = json.loads(urllib.request.urlopen(r).read())\n"
        "    print(json.dumps({'id': q['id'],\n"
        "        'answer': b['choices'][0]['message']['content'], 'source_ids': []}), flush=True)\n",
        encoding="utf-8")
    (ADAPTER / "adapter.json").write_text(json.dumps({
        "name": "calling", "model": "m",
        "ingest": ["python3", "selftest/calling/run.py", "ingest", "--corpus", "{corpus}", "--state", "{state}"],
        "answer": ["python3", "selftest/calling/run.py", "answer", "--state", "{state}"],
    }, indent=2) + "\n", encoding="utf-8")
    yield
    for child in ADAPTER.iterdir():
        child.unlink()
    ADAPTER.rmdir()


def _upstream(usage: dict | None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = {"choices": [{"message": {"content": "60%"}}], "model": "m"}
            if usage is not None:
                payload["usage"] = usage
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _run(tmp_path: Path, usage: dict | None) -> dict:
    server = _upstream(usage)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "bench.runner", "--adapter", str(ADAPTER),
             "--corpus", str(SELFTEST / "corpus"),
             "--questions", str(SELFTEST / "questions.jsonl"),
             "--gold", str(SELFTEST / "gold.jsonl"),
             "--out", str(tmp_path / "run"), "--timeout-seconds", "120"],
            cwd=REPO, capture_output=True, text=True, timeout=300,
            env={**os.environ,
                 "MNEMO_UPSTREAM": f"http://127.0.0.1:{server.server_address[1]}",
                 "OPENAI_API_KEY": "stub"},
        )
        assert completed.returncode == 0, completed.stderr[-1500:]
        return json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))
    finally:
        server.shutdown()
        server.server_close()


def test_an_endpoint_that_returns_usage_produces_a_valid_counted_run(tmp_path):
    report = _run(tmp_path, {"prompt_tokens": 10, "completion_tokens": 2})
    accounting = report["accounting"]
    assert accounting["method"] == "proxy"
    assert accounting["uncounted_calls"] == 0
    assert accounting["forwarded_calls"] == 6
    assert report.get("valid") is not False
    assert report["cost"]["answer_input_tokens"] == 60


def test_an_endpoint_that_omits_usage_invalidates_the_run(tmp_path):
    """The defect: six real calls used to report a cost of zero, and pass."""
    report = _run(tmp_path, None)
    accounting = report["accounting"]
    assert accounting["forwarded_calls"] == 6, "the proxy must count what it forwarded"
    assert accounting["uncounted_calls"] == 6
    assert accounting["method"] == "partial"
    assert report["valid"] is False
    assert "no countable usage" in report["invalid_reason"]


def test_the_offline_fixtures_declare_that_they_measure_nothing(tmp_path):
    """The fixture adapters make no model call, and say so.

    Before the accounting mode existed they produced a `none-observed` row
    that looked like a measured zero. Declaring `local` makes the silence
    intentional and keeps the row out of cost comparisons.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--adapter", str(SELFTEST / "oracle"),
         "--corpus", str(SELFTEST / "corpus"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--out", str(tmp_path / "run"), "--timeout-seconds", "120"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
        env={**os.environ, "OPENAI_API_KEY": "stub"})
    assert completed.returncode == 0, completed.stderr[-1500:]
    accounting = json.loads((tmp_path / "run" / "report.json").read_text())["accounting"]
    assert accounting["declared"] == "local"
    assert accounting["forwarded_calls"] == 0
    assert accounting["method"] == "local-unmeasured"
    assert accounting["comparable_on_cost"] is False


def test_equal_token_costs_stay_equal(tmp_path):
    """Two runs against the same endpoint must report the same cost."""
    first = _run(tmp_path / "a", {"prompt_tokens": 7, "completion_tokens": 3})
    second = _run(tmp_path / "b", {"prompt_tokens": 7, "completion_tokens": 3})
    assert first["cost"]["answer_input_tokens"] == second["cost"]["answer_input_tokens"]
    assert first["cost"]["answer_output_tokens"] == second["cost"]["answer_output_tokens"]
    assert first["accounting"]["uncounted_calls"] == second["accounting"]["uncounted_calls"] == 0


def _bypassing_adapter(tmp_path: Path, declared: str) -> Path:
    """An adapter that answers without any model call at all."""
    d = tmp_path / f"bypass-{declared}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.py").write_text(
        "import json, sys\n"
        "if sys.argv[1] == 'ingest':\n    sys.exit(0)\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n        continue\n"
        "    print(json.dumps({'id': json.loads(line)['id'],\n"
        "        'answer': '60%', 'source_ids': []}), flush=True)\n", encoding="utf-8")
    (d / "adapter.json").write_text(json.dumps({
        "name": f"bypass-{declared}", "model": "m", "accounting": declared,
        "ingest": ["python3", str(d / "run.py"), "ingest", "--corpus", "{corpus}", "--state", "{state}"],
        "answer": ["python3", str(d / "run.py"), "answer", "--state", "{state}"],
    }, indent=2) + "\n", encoding="utf-8")
    return d


def _run_adapter(adapter: Path, out: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--adapter", str(adapter),
         "--corpus", str(SELFTEST / "corpus"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--out", str(out), "--timeout-seconds", "120"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
        env={**os.environ, "OPENAI_API_KEY": "stub"})
    assert completed.returncode == 0, completed.stderr[-1500:]
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_a_bypassed_remote_call_cannot_produce_a_valid_cost_row(tmp_path):
    """Silence from an adapter that promised proxy accounting is a bypass.

    The missing-usage case already failed closed; this is its other half. The
    run still produces a score, and the score may even be right, but nothing
    measured what it cost, so the row must not be valid or cost-comparable.
    """
    report = _run_adapter(_bypassing_adapter(tmp_path, "proxy"), tmp_path / "run")
    accounting = report["accounting"]
    assert accounting["declared"] == "proxy"
    assert accounting["forwarded_calls"] == 0
    assert accounting["method"] == "declared-proxy-but-silent"
    assert accounting["comparable_on_cost"] is False
    assert report["valid"] is False
    assert "no request crossed the proxy" in report["invalid_reason"]
    # The score exists; it is the cost that was never observed.
    assert report["summary"]["accuracy_overall"] > 0


def test_an_adapter_that_declares_a_local_model_stays_valid_but_uncomparable(tmp_path):
    """Honest silence is allowed, and still kept out of cost comparisons."""
    report = _run_adapter(_bypassing_adapter(tmp_path, "local"), tmp_path / "run")
    accounting = report["accounting"]
    assert accounting["method"] == "local-unmeasured"
    assert accounting["comparable_on_cost"] is False
    assert report.get("valid") is not False


def test_an_unknown_accounting_mode_is_refused(tmp_path):
    adapter = _bypassing_adapter(tmp_path, "proxy")
    spec = json.loads((adapter / "adapter.json").read_text())
    spec["accounting"] = "whatever"
    (adapter / "adapter.json").write_text(json.dumps(spec), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--adapter", str(adapter),
         "--corpus", str(SELFTEST / "corpus"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--out", str(tmp_path / "run"), "--timeout-seconds", "60"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert completed.returncode != 0
    assert "expected one of" in completed.stderr


def test_a_counted_run_is_the_only_shape_marked_cost_comparable(tmp_path):
    report = _run(tmp_path, {"prompt_tokens": 4, "completion_tokens": 1})
    assert report["accounting"]["comparable_on_cost"] is True
