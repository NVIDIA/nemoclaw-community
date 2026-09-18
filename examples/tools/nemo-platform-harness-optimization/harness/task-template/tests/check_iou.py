#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Surface the host-measured IoU as a metric the loop can gate on.

The wrapper scores the built document against its reference mesh on the host and
publishes the number as an `eval.iou` span. This reads it back out. It measures
nothing itself — it only makes ground truth visible to a container-bound verifier.
"""
import json
import os
import pathlib
import sys

TRACE_DIR = pathlib.Path(os.environ["TRACE_DIR"])
OUT = pathlib.Path("/logs/verifier/metric_eval_iou.json")

files = sorted(TRACE_DIR.glob("*.jsonl"))
if not files:
    sys.exit(f"no trace files in {TRACE_DIR}")

value = None
for path in files:
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        for resource in json.loads(line).get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    for attr in span.get("attributes", []):
                        if attr.get("key") == "eval.iou":
                            value = float(attr["value"]["stringValue"])

if value is None:
    # No score was published. That is missing evidence, not a zero — a failed
    # scorer must not look like a failed reconstruction.
    sys.exit("no eval.iou span in trace; the host scorer did not publish a result")

OUT.write_text(json.dumps({"eval_iou": max(0.0, min(1.0, value))}))
print(f"eval_iou={value:.4f}", file=sys.stderr)
