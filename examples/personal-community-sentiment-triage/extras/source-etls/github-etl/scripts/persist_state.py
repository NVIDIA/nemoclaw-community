#!/usr/bin/env python3
"""Pass Singer messages through while capturing the latest STATE message."""

from __future__ import annotations

import json
import os
import sys
import tempfile


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: persist_state.py <state-path>", file=sys.stderr)
        return 2

    state_path = sys.argv[1]
    state_dir = os.path.dirname(state_path) or "."
    os.makedirs(state_dir, exist_ok=True)

    latest_state = None

    for raw_line in sys.stdin:
        sys.stdout.write(raw_line)
        if not raw_line.strip():
            continue
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if message.get("type") == "STATE":
            latest_state = message.get("value")

    sys.stdout.flush()

    if latest_state is None:
        return 0

    with tempfile.NamedTemporaryFile(
        "w",
        dir=state_dir,
        delete=False,
        encoding="utf-8",
    ) as handle:
        json.dump(latest_state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = handle.name

    os.replace(temp_path, state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
