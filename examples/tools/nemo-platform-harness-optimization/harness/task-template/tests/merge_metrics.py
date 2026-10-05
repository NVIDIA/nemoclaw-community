#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Merge every metric_*.json under /logs/verifier into reward.json."""
import glob
import json
import pathlib

result: dict[str, float] = {}
for path in sorted(glob.glob("/logs/verifier/metric_*.json")):
    with open(path) as handle:
        result.update(json.load(handle))

pathlib.Path("/logs/verifier/reward.json").write_text(json.dumps(result))
print(f"reward.json={result}")
