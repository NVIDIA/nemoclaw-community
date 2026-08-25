#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""An adapter that gets every question wrong, one way per grading mode.

Answers are hard-coded, not derived from the answer key: this adapter is never
given the key, exactly like a real one. It exists so the scoring path can be
exercised end to end without a model, a network, or an API key.
"""

from __future__ import annotations

import json
import sys

ANSWERS = {
    "st-freshness": {
        "answer": "It is still at 20%.",
        "source_ids": []
    },
    "st-require-all": {
        "answer": "It is 55,000.",
        "source_ids": []
    },
    "st-abstain": {
        "answer": "It completed on 12 March.",
        "source_ids": []
    },
    "st-boolean": {
        "answer": "Yes, it uses the queue.",
        "source_ids": []
    },
    "st-ordering": {
        "answer": "pilot, then design review, then kickoff.",
        "source_ids": []
    },
    "st-citation": {
        "answer": "The message queue.",
        "source_ids": []
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
