#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Deep Research Sandbox Client for OpenClaw.
"""
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

LAST_TASK_DIR = os.path.join(os.path.expanduser("~"), ".deep-research")
LAST_TASK_PATH = os.path.join(LAST_TASK_DIR, "last-task")
DEPTH_TIMEOUTS = {"shallow": 300, "standard": 900, "deep": 2400}


def _usage(exit_code: int = 1) -> None:
    print('Usage: deep-research [options] "<research prompt or goal>"', file=sys.stderr)
    print("Options:", file=sys.stderr)
    print("  --depth <shallow|standard|deep>", file=sys.stderr)
    print('  --rubric "<text>"', file=sys.stderr)
    print("  --resume <task_id>", file=sys.stderr)
    print("  --resume-last", file=sys.stderr)
    print("  --list [N]", file=sys.stderr)
    print("  --timeout <seconds>", file=sys.stderr)
    print("  --json", file=sys.stderr)
    print("  --output <path>", file=sys.stderr)
    print("  --task-id-only", file=sys.stderr)
    sys.exit(exit_code)


def _write_last_task(task_id: str) -> None:
    os.makedirs(LAST_TASK_DIR, exist_ok=True)
    with open(LAST_TASK_PATH, "w", encoding="utf-8") as handle:
        handle.write(task_id)


def _read_last_task() -> str:
    with open(LAST_TASK_PATH, "r", encoding="utf-8") as handle:
        task_id = handle.read().strip()
    if not task_id:
        raise ValueError("last-task file is empty")
    return task_id


def _request_json(url: str, *, method: str = "GET", headers: Optional[Dict[str, str]] = None, body: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _truncate(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _parse_last_activity_age_seconds(last_activity: Optional[str]) -> Optional[int]:
    if not last_activity:
        return None
    try:
        activity_dt = datetime.fromisoformat(last_activity)
        if activity_dt.tzinfo is None:
            activity_dt = activity_dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - activity_dt.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None


class ProgressRenderer:
    def __init__(self) -> None:
        self._is_tty = sys.stderr.isatty()
        self._last_logged_second = -30
        self._last_warning_at = 0.0

    def render(self, elapsed: int, status: str, retry_count: int, max_retries: int, last_activity_age: Optional[int]) -> None:
        activity_text = "unknown"
        if last_activity_age is not None:
            activity_text = f"{last_activity_age}s ago"
        line = f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {status} - attempt {retry_count + 1}/{max_retries + 1} - last activity {activity_text}"
        if self._is_tty:
            sys.stderr.write("\r" + line[:200].ljust(200))
            sys.stderr.flush()
            return
        if elapsed - self._last_logged_second >= 30:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
            self._last_logged_second = elapsed

    def clear(self) -> None:
        if self._is_tty:
            sys.stderr.write("\r" + (" " * 200) + "\r")
            sys.stderr.flush()

    def warn_stuck(self, age_seconds: int) -> None:
        now = time.time()
        if now - self._last_warning_at >= 60:
            sys.stderr.write(f"[warning] no worker activity for {age_seconds}s - task may be stuck\n")
            sys.stderr.flush()
            self._last_warning_at = now


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        _usage(0 if len(sys.argv) >= 2 else 1)

    endpoint_url = os.getenv("DEEPAGENTS_ENDPOINT_URL", "http://host.openshell.internal:9050").rstrip("/")
    secret = os.getenv("DEEPAGENTS_SERVICE_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    depth = "standard"
    rubric: Optional[str] = None
    resume_task_id: Optional[str] = None
    resume_last = False
    list_limit: Optional[int] = None
    timeout_override: Optional[int] = None
    json_output = False
    output_path: Optional[str] = None
    task_id_only = False
    prompt_parts: List[str] = []

    idx = 1
    while idx < len(sys.argv):
        arg = sys.argv[idx]
        if arg == "--depth" and idx + 1 < len(sys.argv):
            depth = sys.argv[idx + 1]
            idx += 2
        elif arg == "--rubric" and idx + 1 < len(sys.argv):
            rubric = sys.argv[idx + 1]
            idx += 2
        elif arg == "--resume" and idx + 1 < len(sys.argv):
            resume_task_id = sys.argv[idx + 1].strip()
            idx += 2
        elif arg == "--resume-last":
            resume_last = True
            idx += 1
        elif arg == "--list":
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
                list_limit = int(sys.argv[idx + 1])
                idx += 2
            else:
                list_limit = 10
                idx += 1
        elif arg == "--timeout" and idx + 1 < len(sys.argv):
            timeout_override = int(sys.argv[idx + 1])
            idx += 2
        elif arg == "--json":
            json_output = True
            idx += 1
        elif arg == "--output" and idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
            idx += 2
        elif arg == "--task-id-only":
            task_id_only = True
            idx += 1
        else:
            prompt_parts.append(arg)
            idx += 1

    if depth not in DEPTH_TIMEOUTS:
        print(f"Error: --depth must be one of shallow, standard, deep; got '{depth}'.", file=sys.stderr)
        sys.exit(2)
    if rubric is not None and not rubric.strip():
        print("Error: --rubric must be non-empty when provided.", file=sys.stderr)
        sys.exit(2)
    prompt = " ".join(prompt_parts).strip()
    if prompt and len(prompt.encode("utf-8")) > 32768:
        print("Error: prompt exceeds 32 KiB limit.", file=sys.stderr)
        sys.exit(2)
    if resume_task_id and prompt:
        print("Error: --resume cannot be combined with a prompt.", file=sys.stderr)
        sys.exit(2)
    if resume_last and prompt:
        print("Error: --resume-last cannot be combined with a prompt.", file=sys.stderr)
        sys.exit(2)
    if task_id_only and (json_output or output_path):
        print("Error: --task-id-only cannot be combined with --json or --output.", file=sys.stderr)
        sys.exit(2)

    if list_limit is not None:
        data = _request_json(f"{endpoint_url}/v1/tasks?limit={list_limit}", headers=headers, timeout=15)
        print("task_id | status | depth | created_at | prompt")
        for task in data.get("tasks", []):
            print(f"{task.get('task_id')} | {task.get('status')} | {task.get('depth')} | {task.get('created_at')} | {_truncate(task.get('prompt', ''))}")
        sys.exit(0)

    if resume_last:
        try:
            resume_task_id = _read_last_task()
        except Exception as exc:
            print(f"Error: could not read last task: {exc}", file=sys.stderr)
            sys.exit(1)

    if not resume_task_id and not prompt:
        _usage(2)

    task_id: Optional[str] = resume_task_id
    status_renderer = ProgressRenderer()
    poll_timeout = timeout_override or DEPTH_TIMEOUTS[depth]
    delete_in_progress = {"done": False}
    current_task_id = {"value": task_id}
    last_sigint = {"time": 0.0}

    def handle_sigint(signum, frame):
        del signum, frame
        now = time.time()
        if now - last_sigint["time"] <= 3:
            sys.exit(130)
        last_sigint["time"] = now
        if not current_task_id["value"]:
            sys.exit(130)
        print(f"Cancelling task {current_task_id['value']}...", file=sys.stderr)
        try:
            _request_json(
                f"{endpoint_url}/v1/tasks/{current_task_id['value']}",
                method="DELETE",
                headers=headers,
                timeout=5,
            )
        except Exception:
            pass
        delete_in_progress["done"] = True
        sys.exit(130)

    signal.signal(signal.SIGINT, handle_sigint)

    if not task_id:
        data = _request_json(
            f"{endpoint_url}/v1/tasks",
            method="POST",
            headers=headers,
            body={"prompt": prompt, "mode": "live", "depth": depth, **({"rubric": rubric} if rubric else {})},
            timeout=15,
        )
        task_id = data.get("task_id")
        if not task_id:
            print(f"Error: server response missing task_id: {data}", file=sys.stderr)
            sys.exit(1)
        current_task_id["value"] = task_id
        _write_last_task(task_id)
        if task_id_only:
            sys.stdout.write(task_id)
            sys.exit(0)
        print(f"Task queued successfully (Task ID: {task_id}).", file=sys.stderr)

    poll_url = f"{endpoint_url}/v1/tasks/{task_id}"
    start_time = time.time()
    consecutive_failures = 0

    while time.time() - start_time < poll_timeout:
        try:
            task_data = _request_json(poll_url, headers=headers, timeout=10)
            consecutive_failures = 0
            current_task_id["value"] = task_id
            status = task_data.get("status")
            retry_count = int(task_data.get("retry_count") or 0)
            max_retries = int(task_data.get("max_retries") or 0)
            last_activity = task_data.get("last_activity_at")
            last_activity_age = _parse_last_activity_age_seconds(last_activity)
            elapsed = int(time.time() - start_time)
            if status == "running" and last_activity_age is not None and last_activity_age > 180:
                status_renderer.warn_stuck(last_activity_age)
            if status == "completed":
                status_renderer.clear()
                duration_seconds = int(time.time() - start_time)
                payload = {
                    "task_id": task_id,
                    "status": status,
                    "depth": task_data.get("depth"),
                    "result": task_data.get("result", ""),
                    "duration_seconds": duration_seconds,
                    "retry_count": retry_count,
                }
                output_text = json.dumps(payload) if json_output else task_data.get("result", "")
                if output_path:
                    with open(output_path, "w", encoding="utf-8") as handle:
                        handle.write(output_text)
                else:
                    print(output_text)
                sys.exit(0)
            if status in ("failed", "cancelled"):
                status_renderer.clear()
                error_msg = task_data.get("error") or f"Task ended with status: {status}"
                print(f"DeepResearch task failed: {error_msg}", file=sys.stderr)
                sys.exit(1)
            status_renderer.render(elapsed, status or "queued", retry_count, max_retries, last_activity_age)
        except urllib.error.HTTPError as exc:
            consecutive_failures += 1
            sleep_seconds = min(4 * (2 ** (consecutive_failures - 1)), 30)
            print(f"Warning: poll request failed ({exc}); retrying in {sleep_seconds}s...", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue
        except Exception as exc:
            consecutive_failures += 1
            sleep_seconds = min(4 * (2 ** (consecutive_failures - 1)), 30)
            print(f"Warning: poll request failed ({exc}); retrying in {sleep_seconds}s...", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue
        time.sleep(4.0)

    status_renderer.clear()
    print(f"Timeout waiting for DeepResearch task {task_id} to complete. Re-run with --resume {task_id}.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
