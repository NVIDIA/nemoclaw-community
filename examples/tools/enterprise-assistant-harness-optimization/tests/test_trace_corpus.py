# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.validate_trace_corpus import validate


def make_corpus(root: Path, *, repeated_prompt: bool = False) -> Path:
    records = []
    families = ["coverage", "read", "retry", "auth", "approval", "json"]
    for index in range(42):
        case_id = f"case-{index:02d}"
        prompt = "Repeated request" if repeated_prompt and index in {0, 1} else f"Distinct request {index}"
        trace_id = f"trace-{index:02d}"
        trace = {
            "schema_version": "ATIF-v1.7",
            "trajectory_id": trace_id,
            "extra": {"logical_case_id": case_id},
            "steps": [{"step_id": 1, "source": "user", "message": prompt}],
        }
        relpath = f"{case_id}.atif.json"
        (root / relpath).write_text(json.dumps(trace))
        records.append(
            {
                "path": relpath,
                "sha256": hashlib.sha256((root / relpath).read_bytes()).hexdigest(),
                "trace_id": trace_id,
                "logical_case_id": case_id,
                "behavior_family": families[index % len(families)],
                "prompt": prompt,
            }
        )
    index_path = root / "index.json"
    (root / "insights.jsonl").write_text("".join(
        json.dumps({"id": record["trace_id"], "attributes": {"task_text": record["prompt"]}}) + "\n"
        for record in records
    ))
    index_path.write_text(json.dumps({"schema": "enterprise-trace-corpus-v2", "traces": records,
        "insights_sha256": hashlib.sha256((root / "insights.jsonl").read_bytes()).hexdigest()}))
    return index_path


class TraceCorpusTest(unittest.TestCase):
    def test_valid_distinct_production_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(validate(make_corpus(Path(raw))), [])

    def test_duplicate_user_requests_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            errors = validate(make_corpus(Path(raw), repeated_prompt=True))
            self.assertTrue(any("prompts must be distinct" in error for error in errors))

    def test_missing_trace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index_path = make_corpus(Path(raw))
            (Path(raw) / "case-00.atif.json").unlink()
            self.assertTrue(any("missing trace" in error for error in validate(index_path)))

    def test_altered_trace_is_rejected_even_with_unchanged_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            index_path = make_corpus(Path(raw))
            path = Path(raw) / "case-00.atif.json"
            trace = json.loads(path.read_text())
            trace["steps"].append({"source": "agent", "message": "Changed answer"})
            path.write_text(json.dumps(trace))
            self.assertTrue(any("trace digest" in error for error in validate(index_path)))

    def test_altered_insights_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            index_path = make_corpus(Path(raw))
            (Path(raw) / "insights.jsonl").write_text('{"changed":true}\n')
            self.assertTrue(any("bundle digest" in error for error in validate(index_path)))

    def test_rehashed_input_cannot_drop_a_source_trace(self):
        with tempfile.TemporaryDirectory() as raw:
            index_path = make_corpus(Path(raw))
            path = Path(raw) / "insights.jsonl"
            path.write_text("\n".join(path.read_text().splitlines()[1:]) + "\n")
            index = json.loads(index_path.read_text())
            index["insights_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            index_path.write_text(json.dumps(index))
            self.assertTrue(any("IDs/count" in error for error in validate(index_path)))

    def test_rehashed_input_cannot_substitute_a_source_request(self):
        with tempfile.TemporaryDirectory() as raw:
            index_path = make_corpus(Path(raw))
            path = Path(raw) / "insights.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[0]["attributes"]["task_text"] = "Different request"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            index = json.loads(index_path.read_text())
            index["insights_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            index_path.write_text(json.dumps(index))
            self.assertTrue(any("prompt differs" in error for error in validate(index_path)))


if __name__ == "__main__":
    unittest.main()
