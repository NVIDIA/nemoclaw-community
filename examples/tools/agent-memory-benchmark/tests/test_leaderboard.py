# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The leaderboard renders from what the runner actually writes.

It did not: the runner writes ``corpus`` as a dict of document counts, and the
leaderboard used that value as part of a grouping key, so the documented
command raised ``TypeError`` on every report the harness produced. Nothing
covered this file, which is why it survived.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
sys.path.insert(0, str(REPO))

from tools.leaderboard import _corpus_label  # noqa: E402


def _run_harness(out: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--adapter", str(SELFTEST / "oracle"),
         "--corpus", str(SELFTEST / "corpus"), "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"), "--out", str(out), "--timeout-seconds", "120"],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-1500:]


def test_the_documented_command_renders_a_table_from_a_real_run(tmp_path):
    runs = tmp_path / "runs"
    _run_harness(runs / "one")
    out = tmp_path / "leaderboard.md"
    completed = subprocess.run(
        [sys.executable, "tools/leaderboard.py", "--runs", str(runs), "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-1500:]
    table = out.read_text(encoding="utf-8")
    assert "selftest-oracle" in table
    assert "| system |" in table


def test_a_corpus_the_labels_do_not_know_is_shown_by_hash_not_called_A():
    """Grouping an unknown corpus under 'A' would silently merge two results."""
    assert _corpus_label({"fingerprint": {"corpus": "e" * 64}}) == "e" * 12
    assert _corpus_label({}) == "unknown"


def test_the_published_corpora_resolve_to_their_letters():
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from bench.fingerprint import hash_tree
    from tools.leaderboard import CORPUS_LABELS

    assert CORPUS_LABELS[hash_tree(REPO / "corpus")] == "A"
    assert CORPUS_LABELS[hash_tree(REPO / "corpus_b" / "corpus")] == "B"
