#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Atomically append confirmed watchtower items to the seen-items state file.

Reads confirmed items as JSON lines on stdin (fields: topic_id, url, title,
run_id) and appends any not already present to the state file, writing it out
with a write-temp-then-rename so a crash never leaves a partially written or
corrupt state file behind.

Call this only after a run's outputs/digest-<run-id>.md and
outputs/changelog-<run-id>.json have both already been written. State must
only advance once the run's output is durable — if the process crashes
before that, the next sweep re-processes the same candidates from
web_search rather than silently losing them.

State file format: {"items": [{"topic_id", "url", "title", "first_seen_run"}]}

Usage:
    <confirmed.jsonl python3 commit_state.py --state <path>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def load_state(state_path: Path) -> dict:
    if not state_path.is_file():
        return {"items": []}
    text = state_path.read_text(encoding="utf-8").strip()
    if not text:
        return {"items": []}
    state = json.loads(text)
    state.setdefault("items", [])
    return state


def write_state_atomically(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.", suffix=".tmp", dir=str(state_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(state, tmp_file, indent=2, sort_keys=True)
            tmp_file.write("\n")
        os.replace(tmp_name, state_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Append confirmed items on stdin (JSON lines: topic_id, url, title, run_id) "
            "to the seen-items state file. Write is atomic (temp file + rename)."
        ),
    )
    parser.add_argument("--state", required=True, type=Path, help="Path to the seen-items state JSON file")
    args = parser.parse_args()

    state = load_state(args.state)
    seen_urls = {item["url"] for item in state["items"]}

    appended = 0
    for lineno, raw_line in enumerate(sys.stdin, start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"error: stdin line {lineno}: invalid JSON: {exc}", file=sys.stderr)
            return 1

        topic_id = item.get("topic_id")
        url = item.get("url")
        title = item.get("title")
        run_id = item.get("run_id")
        if not all([topic_id, url, title, run_id]):
            print(
                f"error: stdin line {lineno}: item missing one of topic_id, url, title, run_id",
                file=sys.stderr,
            )
            return 1

        if url in seen_urls:
            continue

        state["items"].append(
            {"topic_id": topic_id, "url": url, "title": title, "first_seen_run": run_id}
        )
        seen_urls.add(url)
        appended += 1

    write_state_atomically(args.state, state)
    print(f"commit_state: appended {appended} item(s) to {args.state}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
