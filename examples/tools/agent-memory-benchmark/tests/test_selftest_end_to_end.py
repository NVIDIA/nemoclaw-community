# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The whole pipeline, offline, against a fixture whose score is known.

Two adapters run through the real runner over a six-document corpus: one that
answers every question correctly and one that gets every question wrong, in a
different way per grading mode. Their scores are 1.0 and 0.0 and nothing in
between, so a regression anywhere between the runner and the report moves a
number that is pinned here.

No model, no network, no API key.
"""

from __future__ import annotations

import json
import html
import re
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"
TYPES = {"abstention", "citation", "freshness", "multi_source", "ordering", "single_hop"}


def _run_adapter(name: str, out_dir: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "bench.runner",
         "--adapter", str(SELFTEST / name),
         "--corpus", str(SELFTEST / "corpus"),
         "--questions", str(SELFTEST / "questions.jsonl"),
         "--gold", str(SELFTEST / "gold.jsonl"),
         "--out", str(out_dir),
         "--timeout-seconds", "120"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads((out_dir / "report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def oracle(tmp_path_factory) -> dict:
    return _run_adapter("oracle", tmp_path_factory.mktemp("oracle"))


@pytest.fixture(scope="module")
def wrong(tmp_path_factory) -> dict:
    return _run_adapter("wrong", tmp_path_factory.mktemp("wrong"))


def test_oracle_scores_exactly_one(oracle):
    assert oracle["summary"]["accuracy_overall"] == 1.0
    assert set(oracle["summary"]["accuracy_by_type"]) == TYPES
    assert all(v == 1.0 for v in oracle["summary"]["accuracy_by_type"].values())
    assert oracle["answers_missing"] == []


def test_the_failing_adapter_scores_exactly_zero(wrong):
    assert wrong["summary"]["accuracy_overall"] == 0.0
    assert set(wrong["summary"]["accuracy_by_type"]) == TYPES
    assert all(v == 0.0 for v in wrong["summary"]["accuracy_by_type"].values()), (
        "a wrong answer scored as correct in at least one grading mode"
    )


def test_each_grading_mode_fails_for_its_own_stated_reason(wrong, tmp_path_factory):
    """A mode that silently accepted anything would still score zero overall."""
    run_dir = tmp_path_factory.getbasetemp()
    matches = sorted(run_dir.glob("wrong*/verdicts.jsonl"))
    assert matches, "the failing run wrote no verdicts"
    verdicts = {json.loads(line)["question_id"]: json.loads(line)
                for line in matches[0].read_text(encoding="utf-8").splitlines() if line.strip()}
    assert "rejected" in verdicts["st-freshness"]["reason"].lower()
    assert "required element" in verdicts["st-require-all"]["reason"].lower()
    assert "abstention" in verdicts["st-abstain"]["reason"].lower() or \
           "does not support" in verdicts["st-abstain"]["reason"].lower()
    assert "expected no" in verdicts["st-boolean"]["reason"].lower()
    assert "ordered" in verdicts["st-ordering"]["reason"].lower()


def test_the_report_records_what_a_future_reader_needs(oracle):
    assert oracle["schema_version"] >= 1
    assert oracle["adapter"]["name"] == "selftest-oracle"
    assert oracle["adapter"]["revision"]["files_sha256"]
    assert oracle["trial"] == {"index": 1, "of": 1}
    fp = oracle["fingerprint"]
    assert fp["algorithm"] == "sha256-v1"
    assert fp["corpus"] and fp["questions"] and fp["gold"]
    assert oracle["accounting"]["declared"] == "local"
    assert oracle["accounting"]["method"] == "local-unmeasured", (
        "the fixture makes no model calls and declares so"
    )
    assert oracle["accounting"]["comparable_on_cost"] is False


def test_two_runs_of_the_same_adapter_produce_the_same_score(tmp_path):
    """Scoring is deterministic: no judge model, no sampling, no clock."""
    first = _run_adapter("oracle", tmp_path / "a")
    second = _run_adapter("oracle", tmp_path / "b")
    assert first["summary"] == second["summary"]
    assert first["fingerprint"] == second["fingerprint"]


def test_the_screenshot_shows_what_the_self_test_actually_prints(tmp_path):
    """The SVG is drawn by hand, so nothing stops it describing an older run.

    It has already drifted once: it rendered `**1.0**` as `1.0`, and its test
    count had to be edited by hand every time the suite grew. This runs the
    self-test and requires every result line the image claims to appear in the
    output, so the next drift fails here instead of shipping.
    """
    svg = (REPO / "docs" / "assets" / "offline-self-test.svg").read_text(encoding="utf-8")
    claimed = [
        html.unescape(m.group(1)).strip()
        for m in re.finditer(r"<text[^>]*>(.*?)</text>", svg, re.S)
    ]
    result = subprocess.run(
        [sys.executable, "-m", "bench.runner",
         "--adapter", "selftest/oracle",
         "--corpus", "selftest/corpus",
         "--questions", "selftest/questions.jsonl",
         "--gold", "selftest/gold.jsonl",
         "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    printed = [line.strip() for line in result.stdout.splitlines()]

    # Only the lines that assert a result. Chrome, the prompt, and the caption
    # are the image being an image.
    for line in claimed:
        if not line.startswith("*") or line.startswith("* freshness recency-only"):
            continue
        assert line in printed, (
            f"the screenshot claims {line!r}, which the self-test does not print. "
            f"Re-render docs/assets/offline-self-test.svg from a real run.")


def test_the_readme_raster_shows_the_same_run_as_the_svg():
    """The picture a reader sees must carry the same numbers as the checked SVG.

    `scripts/build_catalog.py` allows only raster formats in a README, so the
    image on the page cannot be the SVG the drift check reads. An earlier
    version of this test only asserted both files existed, and passed while the
    PNG still showed a test count nearly a hundred behind the SVG.

    Where OCR is available the two are compared directly. Where it is not, the
    check falls back to requiring the raster to be no older than its source,
    which is weaker but still catches an SVG edited without a re-export.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    shown = re.findall(r"!\[[^\]]*\]\((docs/assets/[^)]+)\)", readme)
    assert shown, "the README no longer shows the offline self-test image"
    svg = REPO / "docs" / "assets" / "offline-self-test.svg"
    assert svg.exists(), (
        "the README shows an exported image and the SVG it came from is gone, "
        "so nothing checks that the picture matches a real run")

    numbers = set(re.findall(r"(\d{2,4}) passed", svg.read_text(encoding="utf-8")))
    assert numbers, "the SVG no longer states a test count"

    for reference in shown:
        raster = REPO / reference
        assert raster.exists(), f"the README shows {reference}, which is missing"
        if raster.suffix == ".svg":
            continue
        if shutil.which("tesseract") is None:
            assert raster.stat().st_mtime >= svg.stat().st_mtime - 1, (
                f"{reference} predates {svg.name}; re-export it. (Install "
                f"tesseract for the stronger comparison.)")
            continue
        with tempfile.TemporaryDirectory() as work:
            stem = Path(work) / "ocr"
            subprocess.run(
                ["tesseract", str(raster), str(stem), "--psm", "6"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            read = stem.with_suffix(".txt").read_text(encoding="utf-8", errors="ignore")
        assert any(f"{n} passed" in read for n in numbers), (
            f"{reference} does not show the test count the SVG states "
            f"({sorted(numbers)}); re-export the raster from {svg.name} so the "
            f"picture a reader sees describes the run the suite checks.")
