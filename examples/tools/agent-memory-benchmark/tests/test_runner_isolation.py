# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The runner's two guarantees to a contributor, tested by exercising them.

Both of these are only worth anything if they hold when an adapter misbehaves,
so each test runs a small adapter that actually misbehaves: one reaches for the
answer key, one refuses to finish, one leaves a child running behind it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.runner import REPO, _assert_isolated, _run  # noqa: E402


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_relative_read_of_the_answer_key_fails_from_the_work_directory(tmp_path):
    """An adapter that opens "corpus_a/questions/answers.jsonl" must not find it.

    This is the defect the work directory exists to close: the runner used to
    launch adapters from the benchmark root, where that relative path resolves.
    """
    assert (REPO / "corpus_a" / "questions" / "answers.jsonl").exists(), "precondition: the key is there to be found"
    work = tmp_path / "work"
    work.mkdir()
    probe = _script(
        tmp_path,
        "probe.py",
        "import pathlib, sys\n"
        "sys.exit(0 if pathlib.Path('gold/answers.jsonl').exists() else 7)\n",
    )
    with pytest.raises(SystemExit) as excinfo:
        _run([sys.executable, str(probe)], os.environ.copy(), work, None, None, "probe", 60)
    assert "exit code 7" in str(excinfo.value), "the key was reachable from the work directory"


def test_a_phase_handed_the_answer_key_refuses_to_start():
    gold = REPO / "corpus_a" / "questions" / "answers.jsonl"
    with pytest.raises(SystemExit) as excinfo:
        _assert_isolated(["run.py", "--gold", str(gold)], {}, "ingest", {"answer key": gold})
    assert "answer key" in str(excinfo.value)


def test_a_phase_handed_the_answer_key_through_the_environment_refuses_to_start():
    gold = REPO / "corpus_a" / "questions" / "answers.jsonl"
    with pytest.raises(SystemExit):
        _assert_isolated(["run.py"], {"SNEAKY": str(gold)}, "ingest", {"answer key": gold})


def test_ingest_may_still_be_given_the_corpus_and_state():
    gold = REPO / "corpus_a" / "questions" / "answers.jsonl"
    questions = REPO / "corpus_a" / "questions" / "questions.jsonl"
    _assert_isolated(
        ["run.py", "--corpus", str(REPO / "corpus_a" / "corpus" / "part_a"), "--state", "/tmp/state"],
        {"PATH": "/usr/bin"},
        "ingest",
        {"answer key": gold, "question set": questions},
    )


def test_an_adapter_that_never_finishes_is_killed_at_the_deadline(tmp_path):
    hang = _script(tmp_path, "hang.py", "import time\ntime.sleep(600)\n")
    started = time.monotonic()
    with pytest.raises(SystemExit) as excinfo:
        _run([sys.executable, str(hang)], os.environ.copy(), tmp_path, None, None, "hang", 2)
    assert "budget" in str(excinfo.value)
    assert time.monotonic() - started < 30, "the deadline did not stop it promptly"


def test_a_child_the_adapter_left_running_is_killed_too(tmp_path):
    """Killing only the process we launched would leave its workers spending tokens."""
    marker = tmp_path / "child-was-still-alive"
    parent = _script(
        tmp_path,
        "parent.py",
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', \"import time, pathlib; time.sleep(6);"
        f" pathlib.Path(r'{marker}').write_text('alive')\"])\n"
        "time.sleep(600)\n",
    )
    with pytest.raises(SystemExit):
        _run([sys.executable, str(parent)], os.environ.copy(), tmp_path, None, None, "parent", 2)
    time.sleep(8)  # past when the orphan would have written, had it survived
    assert not marker.exists(), "a child outlived the killed adapter"
