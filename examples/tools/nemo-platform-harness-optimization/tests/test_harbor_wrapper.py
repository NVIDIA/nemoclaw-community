# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the pure helpers in ``harness/agent_source/harbor_wrapper.py``.

Nothing here touches the network, the NeMo Platform or FreeCAD. The wrapper
guards its ``harbor`` and ``httpx`` imports precisely so these helpers can be
imported and exercised on their own.

The helpers under test are the three places where a mistake produces a
confident, wrong score rather than an error:

* ``_otlp`` - the OpenInference attribute keys a verifier selects spans by. Emit
  a plain ``kind`` key instead of ``openinference.span.kind`` and every tool
  result is invisible: the same trace and the same scorer measured 0.000 before
  the keys were fixed and 0.833 after.
* ``_otlp_id`` - OTLP ids are base64-encoded fixed-width bytes, 8 for a span and
  16 for a trace. Passing Intake's own string ids through makes Intake reject
  the entire payload as an invalid base64-encoded string.
* ``_tool_call_spans`` - de-duplication on each tool call's own ``id``. Every
  model turn replays the whole tool history, so a naive walk emitted one span
  per mention: 1,241 spans for 17 real calls on a measured reconstruction, a
  ~70x inflation of every per-tool count.
"""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXAMPLE_ROOT / "harness" / "agent_source"))

import harbor_wrapper  # noqa: E402


def tool_call(call_id: str, name: str, code: str = "pass") -> dict:
    """One tool call as Intake nests it inside a LangGraph node payload."""
    return {"type": "tool_call", "id": call_id, "name": name, "args": {"code": code}}


def model_span(span_id: str, calls: list[dict], trace_id: str = "01a0a539") -> dict:
    """An Intake span whose JSON output payload carries *calls*."""
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "name": "model",
        "output": json.dumps({"messages": [{"content": calls}]}),
    }


class OtlpIdTests(unittest.TestCase):
    def test_span_id_is_eight_base64_encoded_bytes(self) -> None:
        encoded = harbor_wrapper._otlp_id("span-579fad1c2b3d4e5f", 8)
        self.assertEqual(len(base64.b64decode(encoded)), 8)

    def test_trace_id_is_sixteen_base64_encoded_bytes(self) -> None:
        encoded = harbor_wrapper._otlp_id("01a0a539-6275-7eb0-8a65-ff6b943600d0", 16)
        self.assertEqual(len(base64.b64decode(encoded)), 16)

    def test_hex_digits_are_preserved_in_order(self) -> None:
        # Separators are stripped; the surviving hex drives the bytes, so an id
        # round-trips to something a reader can still line up with Intake.
        self.assertEqual(
            base64.b64decode(harbor_wrapper._otlp_id("01a0-a539", 4)).hex(),
            "01a0a539",
        )

    def test_short_ids_are_right_padded_not_truncated(self) -> None:
        self.assertEqual(
            base64.b64decode(harbor_wrapper._otlp_id("ab", 8)).hex(),
            "ab" + "0" * 14,
        )

    def test_id_with_no_hex_digits_yields_zero_bytes(self) -> None:
        # "zzz" has no hex digits at all. The point is that it still produces a
        # decodable fixed-width id rather than something Intake rejects.
        self.assertEqual(base64.b64decode(harbor_wrapper._otlp_id("zzz", 8)), bytes(8))

    def test_distinct_ids_stay_distinct(self) -> None:
        first = harbor_wrapper._otlp_id("call_aaa111", 8)
        second = harbor_wrapper._otlp_id("call_bbb222", 8)
        self.assertNotEqual(first, second)


class OtlpSpanTests(unittest.TestCase):
    def convert(self, span: dict) -> dict[str, str]:
        converted = harbor_wrapper._otlp(span)
        return {
            attr["key"]: attr["value"]["stringValue"]
            for attr in converted["attributes"]
        }

    def test_openinference_keys_replace_intake_field_names(self) -> None:
        attributes = self.convert(
            {
                "span_id": "span-01",
                "trace_id": "01a0a539",
                "name": "tools",
                "kind": "TOOL",
                "input": "build a mug",
                "output": "done",
                "model": "example-model-8b",
            }
        )
        # These exact keys are what a verifier filters on.
        self.assertEqual(attributes["openinference.span.kind"], "TOOL")
        self.assertEqual(attributes["input.value"], "build a mug")
        self.assertEqual(attributes["output.value"], "done")
        self.assertEqual(attributes["llm.model_name"], "example-model-8b")
        # The un-namespaced Intake field names must not survive the conversion.
        for stale in ("kind", "input", "output", "model"):
            self.assertNotIn(stale, attributes)

    def test_empty_fields_are_dropped_rather_than_emitted_blank(self) -> None:
        attributes = self.convert(
            {
                "span_id": "span-01",
                "trace_id": "01a0a539",
                "name": "model",
                "kind": "CHAIN",
                "input": "",
                "output": None,
                "raw_attributes": {},
            }
        )
        self.assertEqual(list(attributes), ["openinference.span.kind"])

    def test_ids_are_encoded_on_the_converted_span(self) -> None:
        converted = harbor_wrapper._otlp(
            {"span_id": "span-01", "trace_id": "01a0a539", "name": "model"}
        )
        self.assertEqual(len(base64.b64decode(converted["spanId"])), 8)
        self.assertEqual(len(base64.b64decode(converted["traceId"])), 16)
        self.assertEqual(converted["name"], "model")


class ToolCallExtractionTests(unittest.TestCase):
    def test_nested_tool_calls_are_surfaced_as_their_own_spans(self) -> None:
        span = model_span("span-01", [tool_call("call_a1", "execute_code")])
        emitted = harbor_wrapper._tool_call_spans(span)

        self.assertEqual(len(emitted), 1)
        attributes = {
            attr["key"]: attr["value"]["stringValue"]
            for attr in emitted[0]["attributes"]
        }
        # The node name is "model"; the tool name has to be the MCP call, or a
        # metric counting execute_code finds zero on a run that made 17.
        self.assertEqual(emitted[0]["name"], "execute_code")
        self.assertEqual(attributes["tool.name"], "execute_code")
        self.assertEqual(attributes["openinference.span.kind"], "TOOL")
        self.assertEqual(emitted[0]["status"]["code"], "STATUS_CODE_OK")

    def test_a_traceback_in_the_payload_marks_the_span_as_an_error(self) -> None:
        failing = tool_call(
            "call_boom", "execute_code", "Traceback (most recent call last): boom"
        )
        emitted = harbor_wrapper._tool_call_spans(model_span("span-01", [failing]))
        self.assertEqual(emitted[0]["status"]["code"], "STATUS_CODE_ERROR")

    def test_calls_are_found_in_output_raw_attributes_and_input(self) -> None:
        span = {
            "span_id": "span-01",
            "trace_id": "01a0a539",
            "output": json.dumps([tool_call("call_out", "execute_code")]),
            "raw_attributes": json.dumps([tool_call("call_raw", "read_file")]),
            "input": json.dumps([tool_call("call_in", "write_file")]),
        }
        names = {emitted["name"] for emitted in harbor_wrapper._tool_call_spans(span)}
        self.assertEqual(names, {"execute_code", "read_file", "write_file"})

    def test_non_json_and_malformed_payloads_are_ignored(self) -> None:
        span = {
            "span_id": "span-01",
            "trace_id": "01a0a539",
            "output": "the agent said hello",
            "input": "{not valid json",
        }
        self.assertEqual(harbor_wrapper._tool_call_spans(span), [])


class ToolCallDeduplicationTests(unittest.TestCase):
    """The documented ~70x inflation, reproduced in miniature.

    Turn *n* of a model replays every tool call from turns 1..n-1, so a trace
    with 17 real calls carries 1 + 2 + ... + 17 mentions of them across its
    spans. Keyed on each call's own id, those mentions collapse back to 17.
    """

    def replayed_trace(self, call_count: int) -> list[dict]:
        """One span per model turn, each replaying the full history so far."""
        calls = [
            tool_call(f"call_{index:03d}", "execute_code", f"step {index}")
            for index in range(call_count)
        ]
        return [
            model_span(f"span-{turn:03d}", calls[: turn + 1])
            for turn in range(call_count)
        ]

    def test_a_repeated_call_is_emitted_once_across_spans(self) -> None:
        repeated = tool_call("call_a1", "execute_code")
        spans = [
            model_span("span-01", [repeated]),
            model_span("span-02", [repeated]),
            model_span("span-03", [repeated]),
        ]
        seen: set[str] = set()
        emitted = [out for span in spans for out in harbor_wrapper._tool_call_spans(span, seen)]
        self.assertEqual(len(emitted), 1)

    def test_seventeen_real_calls_survive_a_full_replay(self) -> None:
        spans = self.replayed_trace(17)
        mentions = sum(
            len(json.loads(span["output"])["messages"][0]["content"]) for span in spans
        )
        self.assertEqual(mentions, 153)  # 1 + 2 + ... + 17

        seen: set[str] = set()
        emitted = [out for span in spans for out in harbor_wrapper._tool_call_spans(span, seen)]

        self.assertEqual(len(emitted), 17)
        self.assertEqual(len({out["spanId"] for out in emitted}), 17)

    def test_without_a_shared_set_every_replay_is_emitted(self) -> None:
        # The bug this guards against: de-duplicating per span instead of per
        # trace leaves the inflation fully intact.
        spans = self.replayed_trace(17)
        emitted = [out for span in spans for out in harbor_wrapper._tool_call_spans(span)]
        self.assertEqual(len(emitted), 153)

    def test_distinct_calls_to_the_same_tool_are_kept_apart(self) -> None:
        # Identical name and identical arguments, different ids: a retry of the
        # same code is two real calls and must not collapse to one.
        spans = [
            model_span("span-01", [tool_call("call_a1", "execute_code", "same")]),
            model_span("span-02", [tool_call("call_a2", "execute_code", "same")]),
        ]
        seen: set[str] = set()
        emitted = [out for span in spans for out in harbor_wrapper._tool_call_spans(span, seen)]
        self.assertEqual(len(emitted), 2)
        self.assertEqual(len({out["spanId"] for out in emitted}), 2)

    def test_calls_without_an_id_fall_back_to_a_span_scoped_position(self) -> None:
        # Two different calls at position 0 of two different spans must stay
        # distinct, and repeating a span must not re-emit them.
        anonymous_a = {"type": "tool_call", "name": "execute_code", "args": {}}
        anonymous_b = {"type": "tool_call", "name": "read_file", "args": {}}
        seen: set[str] = set()
        first = harbor_wrapper._tool_call_spans(model_span("span-01", [anonymous_a]), seen)
        second = harbor_wrapper._tool_call_spans(model_span("span-02", [anonymous_b]), seen)
        repeat = harbor_wrapper._tool_call_spans(model_span("span-01", [anonymous_a]), seen)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(repeat, [])


class TaskTargetTests(unittest.TestCase):
    """The wrapper recovers its scoring targets from the prompt text alone.

    Its working directory is the run's, not the task's, so the rendered
    instruction is the only task content it reliably receives. That couples
    ``_task_targets`` to the exact shape the shipped instruction uses.
    """

    INSTRUCTION = (
        "Turn the mesh at\n"
        "`/opt/example/meshes/reference_mug.obj`\n"
        "into a fully parametric FreeCAD model.\n\n"
        "Build it in a new FreeCAD document named `EvalMug`.\n"
    )

    def test_document_and_mesh_are_parsed_from_the_instruction(self) -> None:
        document, mesh = harbor_wrapper._task_targets(self.INSTRUCTION)
        self.assertEqual(document, "EvalMug")
        self.assertEqual(mesh, "/opt/example/meshes/reference_mug.obj")

    def test_an_unrendered_placeholder_is_not_mistaken_for_a_path(self) -> None:
        # Guards against the placeholder reaching FreeCAD unresolved:
        # the parse still succeeds, so the failure has to show up downstream as
        # a missing mesh rather than as a plausible one.
        _, mesh = harbor_wrapper._task_targets(
            self.INSTRUCTION.replace("/opt/example/meshes/reference_mug.obj", "@MESH_PATH@")
        )
        self.assertEqual(mesh, "@MESH_PATH@")
        self.assertFalse(Path(mesh).is_absolute())

    def test_missing_targets_yield_empty_strings(self) -> None:
        # _iou_span treats an empty target as "no measurement", never as zero.
        self.assertEqual(harbor_wrapper._task_targets("do something"), ("", ""))


class ScorerPathTests(unittest.TestCase):
    def test_the_default_scorer_path_is_resolved_inside_the_checkout(self) -> None:
        self.assertEqual(
            Path(harbor_wrapper.SCORER), EXAMPLE_ROOT / "scorer" / "score.py"
        )


if __name__ == "__main__":
    unittest.main()
