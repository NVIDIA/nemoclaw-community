# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The guardrail metric, kept outside the candidate's reach.

`eval_iou` is the regression metric the selector uses to drop a candidate that
trades geometry for a better authored score. It therefore must not live in
`agent_source/`, which the optimizer copies into every candidate and invites the
coding agent to edit: a candidate that can rewrite its own guardrail can pass it.

The harness wrapper loads this module from the example root at trial time, so
the code that measures a candidate is never the code a candidate can change.
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def otlp_id(value: str, size: int) -> str:
    """Encode an Intake id as the base64 bytes OTLP requires."""
    digits = re.sub(r"[^0-9a-fA-F]", "", value)[: size * 2].ljust(size * 2, "0")
    return base64.b64encode(bytes.fromhex(digits)).decode()


def iou_span(
    document: str, mesh: str, trace_id: str, scorer: str | Path
) -> dict[str, Any] | None:
    """Score a built document against its reference mesh, as an OTLP span.

    Returns None when the result cannot be measured. Every such path explains
    itself on stderr: without a reason, a harness fault and a genuinely
    unscoreable document are indistinguishable, and both read as agent failure.
    """

    def skip(reason: str) -> None:
        print(f"[eval.iou] not scored for {document!r}: {reason}", file=sys.stderr)
        return None

    if not document or not mesh:
        return skip("no document or mesh parsed from the instruction")
    try:
        done = subprocess.run(
            [sys.executable, str(scorer), document, mesh],
            capture_output=True, text=True, timeout=900,
        )
        # A non-zero exit is void data, not a measured zero. score.py prints
        # nothing to stdout and exits 2 on every failure path, so the exit code
        # is the contract. Recording a failure as 0.0 would be the mistake a
        # guardrail must not make: a floor of 0 protects nothing.
        if done.returncode != 0:
            return skip(f"scorer exit {done.returncode}: {done.stderr.strip()[:200]}")
        iou = float(done.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return skip(f"{type(exc).__name__}: {exc}")
    return {
        "name": "eval.iou",
        "spanId": otlp_id(f"iou{trace_id}", 8),
        "traceId": otlp_id(trace_id, 16),
        "attributes": [
            {"key": "openinference.span.kind", "value": {"stringValue": "TOOL"}},
            {"key": "tool.name", "value": {"stringValue": "eval.iou"}},
            {"key": "eval.iou", "value": {"stringValue": f"{iou:.4f}"}},
            {"key": "tool.output", "value": {"stringValue": f"eval.iou={iou:.4f}"}},
        ],
    }
