"""Small recovery helper for append-only Relay JSONL streams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_relay_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Read Relay events, recovering valid suffix records after an interrupted write."""
    records: list[dict[str, Any]] = []
    recovered_lines: list[int] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
            continue
        except json.JSONDecodeError:
            pass

        marker = '{"atof_version"'
        offsets = [index for index in range(len(line)) if line.startswith(marker, index)]
        suffix_records: list[dict[str, Any]] = []
        for offset in offsets[1:]:
            try:
                candidate = json.loads(line[offset:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                suffix_records.append(candidate)
                break
        if not suffix_records:
            raise ValueError(f"invalid Relay JSONL at {path}:{line_number}")
        records.extend(suffix_records)
        recovered_lines.append(line_number)
    return records, recovered_lines
