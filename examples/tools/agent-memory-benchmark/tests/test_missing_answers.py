# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Silence is not an abstention.

An abstention question is answered correctly by saying the corpus does not
support an answer — a judgement the system had to make. Producing no row at
all is the absence of one. The two used to arrive at the grader identically,
as an empty string, and the abstention grader reads an empty string as a
refusal: a system could score every abstention question by skipping them, and
thirteen missing rows sat under the old majority-based invalidation threshold,
so the run stayed valid.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
sys.path.insert(0, str(REPO))

from bench.grader import grade  # noqa: E402

GOLD = {json.loads(line)["id"]: json.loads(line)
        for line in (SELFTEST / "gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
ABSTAIN = next(g for g in GOLD.values() if g.get("mode") == "abstain")


def test_an_absent_answer_is_not_credited_as_an_abstention():
    verdict = grade(ABSTAIN["id"], "", None, ABSTAIN, answered=False)
    assert verdict.correct is False
    assert "no answer was produced" in verdict.reason


def test_an_explicit_refusal_is_still_credited():
    """The behaviour that must survive the fix."""
    verdict = grade(ABSTAIN["id"], "The corpus does not say.", None, ABSTAIN, answered=True)
    assert verdict.correct is True


def test_an_empty_string_from_a_system_that_did_answer_is_still_a_refusal():
    """A system that returned a row with an empty answer made a (poor) choice."""
    verdict = grade(ABSTAIN["id"], "", None, ABSTAIN, answered=True)
    assert verdict.correct is True


def _skipping_adapter(tmp_path: Path) -> Path:
    d = tmp_path / "skipper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.py").write_text(
        "import json, sys\n"
        "if sys.argv[1] == 'ingest':\n    sys.exit(0)\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n        continue\n"
        "    q = json.loads(line)\n"
        "    if q['type'] == 'abstention':\n        continue\n"
        "    print(json.dumps({'id': q['id'], 'answer': '60%', 'source_ids': []}), flush=True)\n",
        encoding="utf-8")
    (d / "adapter.json").write_text(json.dumps({
        "name": "skipper", "model": "m", "accounting": "local",
        "ingest": ["python3", str(d / "run.py"), "ingest", "--corpus", "{corpus}", "--state", "{state}"],
        "answer": ["python3", str(d / "run.py"), "answer", "--state", "{state}"],
    }, indent=2) + "\n", encoding="utf-8")
    return d


def test_the_runner_gives_no_credit_for_skipped_abstentions(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--adapter", str(_skipping_adapter(tmp_path)),
         "--corpus", str(SELFTEST / "corpus"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--out", str(tmp_path / "run"), "--timeout-seconds", "120"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
        env={**os.environ, "OPENAI_API_KEY": "stub"})
    assert completed.returncode == 0, completed.stderr[-1500:]
    report = json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["accuracy_by_type"]["abstention"] == 0.0
    assert report["answers_missing"]
    assert report["valid"] is False
    assert "received no answer" in report["invalid_reason"]


def test_regrade_records_missing_answers_and_fails_closed(tmp_path):
    """regrade had the same behaviour and kept no record of what was absent."""
    run = tmp_path / "run"
    run.mkdir()
    ids = [json.loads(line)["id"] for line in
           (SELFTEST / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    keep = [i for i in ids if not i.startswith("st-abstain")]
    run.joinpath("answers.jsonl").write_text(
        "\n".join(json.dumps({"id": i, "answer": "60%"}) for i in keep) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/regrade.py", "--run", str(run),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--corpus", str(SELFTEST / "corpus")],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-1500:]
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert report["answers_missing"] == [i for i in ids if i.startswith("st-abstain")]
    assert report["valid"] is False
    assert report["summary"]["accuracy_by_type"]["abstention"] == 0.0


def test_an_aggregation_change_changes_the_fingerprint(tmp_path):
    """report.py produces the published numbers, so it is part of the scorer."""
    from bench.fingerprint import _SCORER, scorer_revision

    assert "report.py" in _SCORER, "the aggregation module must be in the scorer revision"
    before = scorer_revision()
    target = REPO / "bench" / "report.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# an aggregation change\n")
        assert scorer_revision() != before, "editing the aggregator left the fingerprint unchanged"
    finally:
        target.write_bytes(original)
    assert scorer_revision() == before
