# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What the isolation guards do not stop, demonstrated rather than described.

The runner refuses to hand a phase the answer key, and launches adapters from a
scratch directory so a relative open of `corpus_a/questions/answers.jsonl` finds nothing.
Neither of those makes the key unreachable: the benchmark root is on
`PYTHONPATH` so adapters can import `adapters._lib`, and an adapter can use the
same import to locate the key and read it.

This file exists so the limit is a documented, tested fact rather than
something a reader discovers in someone's result. If a future change does make
the key unreachable, this test fails, and that is the moment to update the
README and the runner docstring, which currently say it is reachable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"

PROBE = '''
import json, sys
from pathlib import Path
import bench.runner as r          # PYTHONPATH is set by the runner
key = Path(r.REPO) / "corpus_a" / "questions" / "answers.jsonl"
print(json.dumps({"reachable": key.exists(), "path": str(key)}))
'''


def test_the_guards_reject_a_phase_handed_the_key():
    """The half that does work: the key is never an argument or a variable."""
    from bench.runner import _assert_isolated

    gold = REPO / "corpus_a" / "questions" / "answers.jsonl"
    for argv, env in ([["run.py", "--gold", str(gold)], {}], [["run.py"], {"K": str(gold)}]):
        try:
            _assert_isolated(argv, env, "ingest", {"answer key": gold})
        except SystemExit:
            continue
        raise AssertionError(f"a phase handed the key was allowed to start: {argv} {env}")


def test_an_adapter_can_still_derive_and_read_the_key(tmp_path):
    """The half that does not: PYTHONPATH hands over the root, and the root
    is enough. Documented in README.md under "How the runner treats your
    adapter"; if this ever fails, that section is now wrong."""
    probe = tmp_path / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, capture_output=True, text=True,
        timeout=60, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)},
    )
    assert completed.returncode == 0, completed.stderr[-800:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["reachable"] is True, (
        "the answer key is no longer reachable from an adapter — that is an "
        "improvement, and README.md plus bench/runner.py must stop saying it is"
    )
