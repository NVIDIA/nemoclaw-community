# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Write one JSON record for each case.

A record holds the decision and never the command output. If a denied action
returns protected content, the record says that a leak occurred and omits the
content itself.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Dict, Iterable

from .runner import Outcome

SCHEMA_VERSION = 1


def record(
    outcome: Outcome,
    backend_name: str,
    timestamp: str,
    host_traits: Collection[str] = (),
) -> Dict[str, Any]:
    case = outcome.case
    return {
        "schema": SCHEMA_VERSION,
        "timestamp": timestamp,
        "backend": backend_name,
        "host_traits": sorted(host_traits),
        "case_id": case.case_id,
        "priority": case.priority,
        "expect": case.expect,
        "verdict": outcome.verdict,
        "detail": outcome.detail,
        "exit_code": outcome.exit_code,
        "matched_signature": outcome.matched_signature,
        "leak_detected": outcome.leak_detected,
        "duration_ms": outcome.duration_ms,
    }


def write_jsonl(
    path: Path,
    outcomes: Iterable[Outcome],
    backend_name: str,
    host_traits: Collection[str] = (),
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for outcome in outcomes:
            entry = record(outcome, backend_name, timestamp, host_traits)
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")
