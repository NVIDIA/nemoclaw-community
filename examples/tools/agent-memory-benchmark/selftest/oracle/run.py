#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""An adapter that answers every question correctly.

Answers are hard-coded, not derived from the answer key: this adapter is never
given the key, exactly like a real one. It exists so the scoring path can be
exercised end to end without a model, a network, or an API key.
"""

from __future__ import annotations

import json
import sys

ANSWERS = {
    "st-freshness": {
        "answer": "60%.",
        "source_ids": [
            "E:2027-02-02T09-00-00__bbbb0001"
        ]
    },
    "st-require-all": {
        "answer": "It is now 55,000, revised up from 40,000.",
        "source_ids": [
            "E:2027-02-05T10-00-00__bbbb0002"
        ]
    },
    "st-abstain": {
        "answer": "The corpus does not say.",
        "source_ids": []
    },
    "st-boolean": {
        "answer": "No. Quarry reads through the shared cache.",
        "source_ids": [
            "E:2027-01-10T11-00-00__aaaa0003"
        ]
    },
    "st-ordering": {
        "answer": "kickoff, then design review, then pilot.",
        "source_ids": [
            "E:2027-01-08T10-00-00__aaaa0002"
        ]
    },
    "st-citation": {
        "answer": "The shared cache.",
        "source_ids": [
            "E:2027-01-10T11-00-00__aaaa0003"
        ]
    }
}


def main() -> int:
    if sys.argv[1:2] == ["ingest"]:
        return 0  # nothing to build: the answers are already known
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        question_id = json.loads(line)["id"]
        row = ANSWERS.get(question_id)
        if row is None:
            continue
        print(json.dumps({"id": question_id, **row}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
